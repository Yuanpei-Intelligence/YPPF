"""
Parsers for PKU timetable exports. Pure functions, standard library only.
Contract: ``timetable/README.md`` §4.2.

Supported inputs:

- portal ``getCourseInfo.do`` JSON (``parse_portal_course_json``);
- the portal 我的课表 HTML page with cells ``id="mon1"``..``"sun12"``
  (``parse_portal_html``);
- the elective.pku.edu.cn 选课结果 table, as HTML or as plain text copied
  from a phone (``parse_elective_table``).

Input handling is deliberately tolerant: HTML tags are stripped, ``<br>``
becomes a newline, both ``1-16周`` and ``1~16周`` are accepted, course-name
suffixes such as ``(主)`` are removed, and a cell may carry several 上课信息
lines (different week ranges) which become several blocks.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

__all__ = [
    'LessonBlock',
    'WEEKDAY_KEYS',
    'html_to_text',
    'normalize_text',
    'clean_course_name',
    'parse_course_cell_text',
    'parse_portal_course_json',
    'parse_portal_html',
    'parse_elective_table',
    'parse_week_spec',
    'parse_time_pieces',
    'parse_text',
    'detect_format',
    'external_key',
]


WEEKDAY_KEYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')

_WEEKDAY_CHARS = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 7, '天': 7,
}
_CN_NUMBERS = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8,
    '九': 9, '十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14,
    '十五': 15,
}
_PARITY_BY_CHAR = {'每': 0, '单': 1, '双': 2}

_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_BLOCK_END_RE = re.compile(r'</(?:div|p|tr|li|h\d)\s*>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')
_SPACES_RE = re.compile(r'[ \t　\xa0]+')

_INFO_PREFIX_RE = re.compile(r'^(?:上课信息|上课时间|时间地点)\s*[：:]\s*')
_EXAM_PREFIX_RE = re.compile(r'^(?:考试信息|考试时间|考试安排|考试)\s*[：:]')
# '1-16周', '1~16周', '第5周', '16周'; the end of the range is optional.
_WEEK_RANGE_RE = re.compile(
    r'(?<![\d])(\d{1,2})\s*(?:[-~～－—–至]\s*(\d{1,2}))?\s*周')
_TEACHER_RE = re.compile(
    r'(?:授课教师|教师|老师)\s*[：:]\s*(.*?)'
    r'(?=\s*(?:备注|考试信息|考试)\s*[：:]|\s*$)')
_NOTE_RE = re.compile(r'备注\s*[：:]\s*(.*?)\s*$')
_INFO_CUT_RE = re.compile(r'(?:授课教师|教师|老师|备注)\s*[：:]')
_PARITY_WORD_RE = re.compile(r'每周|单周|双周')
_SEPARATOR_RE = re.compile(r'[,，;；]')

_NAME_TAGS = (
    '主', '双', '辅', '外', '慕课', '通选', '专选', '公选', '限选', '任选',
    '必修', '选修', '英文', '全英文', '重修', '补修', '实验', '习题',
)
_NAME_TAG_RE = re.compile(
    r'\s*[（(]\s*(?:' + '|'.join(_NAME_TAGS) + r')\s*[)）]\s*$')

_PORTAL_CELL_RE = re.compile(
    r'<td\b[^>]*\bid\s*=\s*["\'](mon|tue|wed|thu|fri|sat|sun)(\d{1,2})["\']'
    r'[^>]*>(.*?)</td>',
    re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r'<tr\b([^>]*)>(.*?)</tr>', re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r'<t[dh]\b[^>]*>(.*?)</t[dh]\s*>', re.IGNORECASE | re.DOTALL)
_DATAGRID_ROW_RE = re.compile(r'datagrid-(?:even|odd|all)', re.IGNORECASE)
_COURSE_CODE_RE = re.compile(r'^[0-9A-Za-z]{6,}$')
_NUMERIC_LINE_RE = re.compile(r'^\d+(?:\.\d+)?$')
_FIELD_SPLIT_RE = re.compile(r'\t|\s{2,}')

# '1~16周 每周周二1~2节 理教306'; the weekday char is in 一二三四五六日(天).
# The room runs to the end of the line or to the next time piece.
_ELECTIVE_TIME_RE = re.compile(
    r'(\d{1,2})\s*[-~～－—–]\s*(\d{1,2})\s*周\s*([每单双])\s*周\s*周\s*'
    r'([一二三四五六日天])\s*(\d{1,2})(?:\s*[-~～－—–]\s*(\d{1,2}))?\s*节'
    r'[ \t　\xa0]*([^\n\r]*?)'
    r'(?=[ \t　\xa0]*(?:\d{1,2}\s*[-~～－—–]\s*\d{1,2}\s*周\s*[每单双]\s*周)'
    r'|[ \t　\xa0]*$)',
    re.MULTILINE)

_SECTION_NUMBER_RE = re.compile(r'第?\s*(\d{1,2}|[一二三四五六七八九十]{1,2})\s*节?')


@dataclass
class LessonBlock:
    """One weekly lesson as parsed from an export (not yet stored)."""

    name: str
    teacher: str = ''
    room: str = ''
    course_code: str = ''
    class_no: str = ''
    weekday: int = 0                     # 1..7
    start_section: int = 0
    end_section: int = 0
    week_start: int = 1
    week_end: int = 16
    parity: int = 0                      # 0 all, 1 odd, 2 even
    raw: str = ''
    note: str = ''

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Unify newlines and exotic spaces, strip each line, drop blank lines."""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\xa0', ' ').replace('　', ' ')
    lines = [line.strip() for line in text.split('\n')]
    return '\n'.join(line for line in lines if line)


def html_to_text(fragment: str) -> str:
    """Convert an HTML fragment to text: ``<br>`` → newline, tags removed."""
    text = _BR_RE.sub('\n', fragment or '')
    text = _BLOCK_END_RE.sub('\n', text)
    text = _TAG_RE.sub('', text)
    text = html_lib.unescape(text)
    return normalize_text(text)


def clean_course_name(name: str) -> str:
    """Strip suffix tags such as ``(主)``/``(双)``/``(慕课)`` from a course name."""
    name = _SPACES_RE.sub(' ', name or '').strip()
    while True:
        stripped = _NAME_TAG_RE.sub('', name)
        if stripped == name:
            return name.strip()
        name = stripped


def _parity_from_text(text: str | None) -> int:
    text = (text or '').strip()
    if text.startswith('单'):
        return 1
    if text.startswith('双'):
        return 2
    return 0


def _room_of(info: str) -> str:
    # The room is what remains of a 上课信息 line after the week ranges,
    # the parity word and the 教师/备注 parts are removed.
    cut = _INFO_CUT_RE.search(info)
    text = info[:cut.start()] if cut else info
    text = _WEEK_RANGE_RE.sub(' ', text)
    text = _PARITY_WORD_RE.sub(' ', text)
    text = _SEPARATOR_RE.sub(' ', text)
    return _SPACES_RE.sub(' ', text).strip()


def _parse_info_line(name: str, info: str, raw: str) -> list[dict[str, Any]]:
    info = _SPACES_RE.sub(' ', info).strip()
    if not info:
        return []
    parity = 1 if '单周' in info else 2 if '双周' in info else 0
    teacher_match = _TEACHER_RE.search(info)
    teacher = teacher_match.group(1).strip() if teacher_match else ''
    note_match = _NOTE_RE.search(info)
    note = note_match.group(1).strip() if note_match else ''
    room = _room_of(info)
    ranges: list[tuple[int, int]] = []
    for start, end in _WEEK_RANGE_RE.findall(info):
        week_start = int(start)
        week_end = int(end) if end else week_start
        if week_end < week_start:
            week_start, week_end = week_end, week_start
        ranges.append((week_start, week_end))
    if not ranges:
        ranges.append((1, 16))
    return [
        {
            'name': name,
            'teacher': teacher,
            'room': room,
            'week_start': week_start,
            'week_end': week_end,
            'parity': parity,
            'note': note,
            'raw': raw,
        }
        for week_start, week_end in ranges
    ]


def parse_course_cell_text(text: str) -> list[dict[str, Any]]:
    """
    Parse the text of one timetable cell, e.g.
    ``'课名(主)\\n上课信息：1-16周 每周 理教201 教师：张三 备注：…\\n考试信息：…'``.

    Returns one dict per 上课信息 line with keys ``name``, ``teacher``,
    ``room``, ``week_start``, ``week_end``, ``parity``, ``note`` and ``raw``.
    A cell with a name but no 上课信息 line yields one dict covering weeks
    1–16; an empty cell yields ``[]``.
    """
    text = html_to_text(text)
    name = ''
    infos: list[str] = []
    for line in text.split('\n'):
        if _EXAM_PREFIX_RE.match(line):
            continue
        prefix = _INFO_PREFIX_RE.match(line)
        if prefix:
            infos.append(line[prefix.end():])
            continue
        if name and _WEEK_RANGE_RE.search(line):
            # An unprefixed 上课信息 line after the course name.
            infos.append(line)
            continue
        if not name:
            name = clean_course_name(line)
    if not name:
        return []
    results: list[dict[str, Any]] = []
    for info in infos:
        results.extend(_parse_info_line(name, info, text))
    if not results:
        results.append({
            'name': name, 'teacher': '', 'room': '',
            'week_start': 1, 'week_end': 16, 'parity': 0,
            'note': '', 'raw': text,
        })
    return results


# ---------------------------------------------------------------------------
# portal (我的课表)
# ---------------------------------------------------------------------------

def _section_number(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    match = _SECTION_NUMBER_RE.match(str(value or '').strip())
    if match is None:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return _CN_NUMBERS.get(token)


def _cell_fields(cell: Any) -> tuple[str, str]:
    # (text, parity) of a portal JSON cell, whatever its shape.
    if isinstance(cell, dict):
        text = cell.get('courseName')
        if text is None:
            text = cell.get('name', '')
        return str(text or ''), str(cell.get('parity') or '')
    if isinstance(cell, str):
        return cell, ''
    return '', ''


def _merge_cells(cells: list[tuple[int, int, list[dict[str, Any]]]]) -> list[LessonBlock]:
    # cells: (weekday, section, dicts). Consecutive sections of one weekday
    # with identical (name, weeks, parity, room, teacher) collapse into one
    # block; each dict of a multi-line cell merges independently.
    by_weekday: dict[int, list[tuple[int, list[dict[str, Any]]]]] = {}
    for weekday, section, dicts in cells:
        by_weekday.setdefault(weekday, []).append((section, dicts))
    blocks: list[LessonBlock] = []
    for weekday in sorted(by_weekday):
        open_blocks: dict[tuple, LessonBlock] = {}
        for section, dicts in sorted(by_weekday[weekday], key=lambda item: item[0]):
            next_open: dict[tuple, LessonBlock] = {}
            for data in dicts:
                key = (data['name'], data['week_start'], data['week_end'],
                       data['parity'], data['room'], data['teacher'])
                if key in next_open:
                    continue  # duplicate line inside one cell
                block = open_blocks.get(key)
                if block is not None and block.end_section == section - 1:
                    block.end_section = section
                else:
                    block = LessonBlock(
                        name=data['name'], teacher=data['teacher'],
                        room=data['room'], weekday=weekday,
                        start_section=section, end_section=section,
                        week_start=data['week_start'],
                        week_end=data['week_end'], parity=data['parity'],
                        raw=data.get('raw', ''), note=data.get('note', ''))
                    blocks.append(block)
                next_open[key] = block
            open_blocks = next_open
    blocks.sort(key=lambda b: (b.weekday, b.start_section, b.week_start, b.name))
    return blocks


def parse_portal_course_json(raw: dict | str) -> list[LessonBlock]:
    """
    Parse the portal ``getCourseInfo.do`` payload::

        {"success": true, "course": [{"timeNum": "第一节",
            "mon": {"courseName": "...", "parity": "", "sty": "..."}, ...}]}

    ``courseName`` may be plain text with newlines, HTML with ``<br>`` or
    empty; ``parity`` may be empty, ``单周``, ``双周`` or absent. Consecutive
    sections merge. Raises ``ValueError`` for a payload that is not a
    course table or whose ``success`` is false.
    """
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError('portal payload must be a JSON object')
    if raw.get('success') is False:
        raise ValueError(str(raw.get('remark') or raw.get('msg') or 'portal request failed'))
    rows = raw.get('course')
    if rows is None and isinstance(raw.get('data'), dict):
        rows = raw['data'].get('course')
    if not isinstance(rows, list):
        raise ValueError('portal payload has no "course" list')
    cells: list[tuple[int, int, list[dict[str, Any]]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        section = _section_number(row.get('timeNum'))
        if section is None:
            continue
        for weekday, key in enumerate(WEEKDAY_KEYS, start=1):
            text, parity_text = _cell_fields(row.get(key))
            if not text.strip():
                continue
            dicts = parse_course_cell_text(text)
            cell_parity = _parity_from_text(parity_text)
            if cell_parity:
                for data in dicts:
                    if data['parity'] == 0:
                        data['parity'] = cell_parity
            if dicts:
                cells.append((weekday, section, dicts))
    return _merge_cells(cells)


def parse_portal_html(html: str) -> list[LessonBlock]:
    """Parse the portal 我的课表 page (cells ``id="mon1"``..``"sun12"``)."""
    cells: list[tuple[int, int, list[dict[str, Any]]]] = []
    for match in _PORTAL_CELL_RE.finditer(html or ''):
        weekday = WEEKDAY_KEYS.index(match.group(1).lower()) + 1
        section = int(match.group(2))
        text = html_to_text(match.group(3))
        if not text:
            continue
        dicts = parse_course_cell_text(text)
        if dicts:
            cells.append((weekday, section, dicts))
    return _merge_cells(cells)


# ---------------------------------------------------------------------------
# elective.pku.edu.cn 选课结果
# ---------------------------------------------------------------------------

def parse_week_spec(text: str) -> tuple[list[tuple[int, int]], int]:
    """
    Week ranges and parity written in ``text``: ``'1-16周'``,
    ``'1~8周,10-16周'`` and ``'第5周'`` give ranges (a reversed range is
    swapped); ``单周``/``双周`` give parity 1/2, anything else 0. Returns
    ``([], 0)`` when no range is present.
    """
    text = text or ''
    ranges: list[tuple[int, int]] = []
    for start, end in _WEEK_RANGE_RE.findall(text):
        week_start = int(start)
        week_end = int(end) if end else week_start
        if week_end < week_start:
            week_start, week_end = week_end, week_start
        ranges.append((week_start, week_end))
    parity = 1 if '单周' in text else 2 if '双周' in text else 0
    return ranges, parity


def parse_time_pieces(text: str) -> list[dict[str, Any]]:
    """
    Every ``'1~16周 每周周二1~2节 理教306'`` piece of the elective time
    format in ``text`` as a dict with ``weekday``, ``start_section``,
    ``end_section``, ``week_start``, ``week_end``, ``parity`` and ``room``.
    """
    pieces: list[dict[str, Any]] = []
    for match in _ELECTIVE_TIME_RE.finditer(text or ''):
        (week_start, week_end, parity_char, weekday_char,
         start_section, end_section, room) = match.groups()
        pieces.append({
            'weekday': _WEEKDAY_CHARS[weekday_char],
            'start_section': int(start_section),
            'end_section': int(end_section or start_section),
            'week_start': int(week_start),
            'week_end': int(week_end),
            'parity': _PARITY_BY_CHAR[parity_char],
            'room': room.strip(' ,，;；'),
        })
    return pieces


def _elective_blocks(name: str, text: str, raw: str, *, teacher: str = '',
                     class_no: str = '', course_code: str = '') -> list[LessonBlock]:
    return [
        LessonBlock(
            name=name, teacher=teacher, room=piece['room'],
            course_code=course_code, class_no=class_no,
            weekday=piece['weekday'],
            start_section=piece['start_section'],
            end_section=piece['end_section'],
            week_start=piece['week_start'], week_end=piece['week_end'],
            parity=piece['parity'], raw=raw)
        for piece in parse_time_pieces(text)
    ]


def _parse_elective_html(html: str) -> list[LessonBlock]:
    rows = _ROW_RE.findall(html)
    datagrid_rows = [(attrs, body) for attrs, body in rows if _DATAGRID_ROW_RE.search(attrs)]
    if datagrid_rows:
        rows = datagrid_rows
    blocks: list[LessonBlock] = []
    for _attrs, body in rows:
        cells = [html_to_text(cell) for cell in _CELL_RE.findall(body)]
        if len(cells) < 9:
            continue
        if any('未选上' in cell for cell in cells):
            continue
        name = clean_course_name(cells[1])
        if not name:
            continue
        time_text = cells[8]
        if not _ELECTIVE_TIME_RE.search(time_text):
            # Column layout differs; take the first cell that holds a time.
            candidates = [cell for cell in cells if _ELECTIVE_TIME_RE.search(cell)]
            if not candidates:
                continue
            time_text = candidates[0]
        course_code = cells[0] if _COURSE_CODE_RE.match(cells[0]) else ''
        blocks.extend(_elective_blocks(
            name, time_text, ' | '.join(cell for cell in cells if cell),
            teacher=cells[5], class_no=cells[6], course_code=course_code))
    return blocks


def _parse_elective_plain(text: str) -> list[LessonBlock]:
    # Line based: every time piece becomes a block; the course name is the
    # text before the first time piece on the same line, otherwise the
    # nearest preceding line that is neither a time piece nor a bare number.
    blocks: list[LessonBlock] = []
    previous_name = ''
    for line in normalize_text(text).split('\n'):
        matches = list(_ELECTIVE_TIME_RE.finditer(line))
        if not matches:
            if not _NUMERIC_LINE_RE.match(line):
                previous_name = line
            continue
        if '未选上' in line:
            continue
        header = line[:matches[0].start()].strip()
        fields = [part.strip() for part in _FIELD_SPLIT_RE.split(header) if part.strip()]
        teacher = class_no = course_code = ''
        if len(fields) >= 8:
            # A whole table row pasted with tab separators: same columns as
            # the HTML table.
            name = clean_course_name(fields[1])
            teacher, class_no = fields[5], fields[6]
            course_code = fields[0] if _COURSE_CODE_RE.match(fields[0]) else ''
        elif fields:
            name = clean_course_name(fields[0])
        else:
            name = clean_course_name(previous_name)
        if not name:
            continue
        blocks.extend(_elective_blocks(
            name, line[matches[0].start():], line,
            teacher=teacher, class_no=class_no, course_code=course_code))
    return blocks


def parse_elective_table(text: str) -> list[LessonBlock]:
    """
    Parse the elective 选课结果 table, either as HTML (``.datagrid`` rows:
    课程名 in the 2nd cell, 教师 6th, 班号 7th, 上课信息 9th; ``未选上`` rows
    skipped) or as plain text copied from a phone (line based).
    """
    text = text or ''
    if re.search(r'<t(?:able|r|d)\b', text, re.IGNORECASE):
        blocks = _parse_elective_html(text)
        if blocks or 'datagrid' in text:
            return blocks
        return _parse_elective_plain(html_to_text(text))
    return _parse_elective_plain(text)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def detect_format(text: str) -> str:
    """
    Guess the format of pasted text: ``'portal_html'``, ``'elective'``,
    ``'portal_json'`` (a pasted ``getCourseInfo.do`` payload) or
    ``'unknown'``.
    """
    text = (text or '').strip()
    if not text:
        return 'unknown'
    if text[0] in '{[':
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict) and ('course' in data or 'timeNum' in text):
            return 'portal_json'
    if _PORTAL_CELL_RE.search(text):
        return 'portal_html'
    if 'datagrid' in text or _ELECTIVE_TIME_RE.search(text):
        return 'elective'
    return 'unknown'


def parse_text(text: str) -> tuple[str, list[LessonBlock]]:
    """Detect the format of pasted text and parse it; ``('unknown', [])`` if none."""
    fmt = detect_format(text)
    if fmt == 'portal_html':
        return fmt, parse_portal_html(text)
    if fmt == 'elective':
        return fmt, parse_elective_table(text)
    if fmt == 'portal_json':
        try:
            return fmt, parse_portal_course_json(text)
        except ValueError:
            return fmt, []
    return fmt, []


def _normalize_key_part(value: str) -> str:
    return _SPACES_RE.sub(' ', (value or '')).strip().lower()


def external_key(block: LessonBlock) -> str:
    """
    sha1 over the normalised identity of a block: name, weekday, sections,
    week range and parity. Room and teacher are deliberately excluded so a
    room change updates the stored entry instead of replacing it.
    """
    parts = [
        _normalize_key_part(block.name),
        str(int(block.weekday)),
        str(int(block.start_section)),
        str(int(block.end_section)),
        str(int(block.week_start)),
        str(int(block.week_end)),
        str(int(block.parity)),
    ]
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()
