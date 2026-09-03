"""解析北大门户「我的课表」另存为的 HTML 文件。

设计目标：
- 纯标准库实现，零第三方依赖，便于在任意环境运行与测试。
- 不触碰任何账号密码：输入只是同学自己「网页另存为」的课表页面，
  不含凭证；解析后只保留结构化课程信息。
- 解析单位格（id=mon1..sun12）中的 courseName 文本，提取课名 / 周次 /
  单双周 / 教室 / 教师 / 考试，并按连续节次合并。

weekday 约定：0=周一 … 6=周日（与 datetime.weekday() 一致）。
parity 约定：'ALL' 每周 / 'ODD' 单周 / 'EVEN' 双周。
"""
import re
import html
from datetime import date, datetime, time, timedelta

__all__ = [
    'parse_pku_course_html',
    'expand_lesson_to_events',
    'PKU_SECTION_TIMES',
]

# 单元格 id 前缀 -> weekday（0=周一）
_DAY_KEY_TO_WEEKDAY = {
    'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
    'fri': 4, 'sat': 5, 'sun': 6,
}

# 节次 -> (开始, 结束) 时间（北大校本部/燕园标准，待学院确认可调整）
PKU_SECTION_TIMES = {
    1: ('08:00', '08:45'), 2: ('08:55', '09:40'),
    3: ('10:00', '10:45'), 4: ('10:55', '11:40'),
    5: ('13:00', '13:45'), 6: ('13:55', '14:40'),
    7: ('15:00', '15:45'), 8: ('15:55', '16:40'),
    9: ('17:00', '17:45'), 10: ('19:00', '19:45'),
    11: ('19:55', '20:40'), 12: ('20:50', '21:35'),
}

# 匹配 id=mon1..sun12 的单元格，并捕获其内部 <span> 文本
_CELL_RE = re.compile(
    r'id="(mon|tue|wed|thu|fri|sat|sun)(\d+)"[^>]*>.*?<span[^>]*>(.*?)</span>',
    re.S,
)
# 上课信息行：N-M周 每周|单周|双周 [教室] 教师：X [备注：Y]
_COURSE_INFO_RE = re.compile(
    r'(\d+)-(\d+)周\s*(每周|单周|双周)?\s*(\S*?)\s*教师：([^\s备注]+?)\s*(备注：(.*))?$'
)


def _clean_text(raw: str) -> str:
    """去掉标签、还原 <br> 为换行、反转义。"""
    raw = re.sub(r'<br\s*/?>', '\n', raw)
    raw = re.sub(r'<[^>]+>', '', raw)
    return html.unescape(raw).strip()


def _parse_course_text(text: str) -> dict | None:
    """解析单格 courseName 文本，返回规范化课程块或 None。"""
    text = _clean_text(text)
    if not text:
        return None
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    if not lines:
        return None
    # 第一行：课名（去掉 (主)/(双)/(辅)/(外)/(慕课) 等后缀）
    name = re.sub(r'\((主|双|辅|外|慕课)\)$', '', lines[0]).strip()
    info = {
        'name': name,
        'week_start': None, 'week_end': None,
        'parity': 'ALL', 'room': '', 'teacher': '', 'exam': '',
    }
    for ln in lines[1:]:
        if ln.startswith('上课信息'):
            m = _COURSE_INFO_RE.search(ln)
            if m:
                info['week_start'] = int(m.group(1))
                info['week_end'] = int(m.group(2))
                info['parity'] = {'每周': 'ALL', '单周': 'ODD', '双周': 'EVEN'}.get(
                    m.group(3), 'ALL')
                info['room'] = m.group(4) or ''
                info['teacher'] = m.group(5)
        elif ln.startswith('考试信息'):
            info['exam'] = ln.replace('考试信息：', '').strip()
    if info['week_start'] is None:
        return None
    return info


def _section_range_to_times(start_section: int, end_section: int):
    """节次区间 -> (开始时间 str, 结束时间 str)，缺失节次回退占位。"""
    start = PKU_SECTION_TIMES.get(start_section, ('00:00', '00:00'))[0]
    end = PKU_SECTION_TIMES.get(end_section, ('00:00', '00:00'))[1]
    return start, end


def parse_pku_course_html(html_text: str) -> list[dict]:
    """解析门户课表 HTML，返回合并后的课程块列表。

    每个课程块字段：
        day_of_week, start_section, end_section, start_time, end_time,
        week_start, week_end, parity, name, room, teacher, exam
    """
    cells = []
    for m in _CELL_RE.finditer(html_text):
        day_key, sec, raw = m.group(1), int(m.group(2)), m.group(3)
        info = _parse_course_text(raw)
        if info:
            cells.append((_DAY_KEY_TO_WEEKDAY[day_key], sec, info))
    cells.sort(key=lambda c: (c[0], c[1]))

    lessons = []
    i = 0
    while i < len(cells):
        day, sec, info = cells[i]
        j = i
        # 合并同 (星期,课名,周次,单双周) 的连续节次
        while (j + 1 < len(cells)
               and cells[j + 1][0] == day
               and cells[j + 1][1] == sec + (j - i + 1)
               and cells[j + 1][2]['name'] == info['name']
               and cells[j + 1][2]['week_start'] == info['week_start']
               and cells[j + 1][2]['week_end'] == info['week_end']
               and cells[j + 1][2]['parity'] == info['parity']):
            j += 1
        end_sec = cells[j][1]
        start_time, end_time = _section_range_to_times(sec, end_sec)
        lessons.append({
            'day_of_week': day,
            'start_section': sec,
            'end_section': end_sec,
            'start_time': start_time,
            'end_time': end_time,
            'week_start': info['week_start'],
            'week_end': info['week_end'],
            'parity': info['parity'],
            'name': info['name'],
            'room': info['room'],
            'teacher': info['teacher'],
            'exam': info['exam'],
        })
        i = j + 1
    return lessons


def expand_lesson_to_events(lesson: dict, semester_start: date,
                            now: datetime | None = None) -> list[dict]:
    """把单条课程块按周展开为具体日历事件（仅保留未来事件）。

    semester_start: 学期第 1 教学周对应的周一日期。
    返回 [{title, start, end, location}, ...]，start/end 为 ISO 字符串。
    """
    if now is None:
        now = datetime.now()
    base = semester_start
    start_t = datetime.strptime(lesson['start_time'], '%H:%M').time()
    end_t = datetime.strptime(lesson['end_time'], '%H:%M').time()
    events = []
    for week in range(lesson['week_start'], lesson['week_end'] + 1):
        if lesson['parity'] == 'ODD' and week % 2 == 0:
            continue
        if lesson['parity'] == 'EVEN' and week % 2 == 1:
            continue
        day = base + timedelta(days=7 * (week - 1) + lesson['day_of_week'])
        start_dt = datetime.combine(day, start_t)
        end_dt = datetime.combine(day, end_t)
        if end_dt <= now:
            continue
        events.append({
            'title': lesson['name'],
            'start': start_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': end_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'location': lesson['room'] or '未设置',
        })
    return events
