# 2025年度总结数据导出脚本

# 引入必要的库
import json
from collections import defaultdict
from datetime import datetime, time, date, timedelta
from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Q, Sum
from app.models import *
from Appointment.models import Appoint, CardCheckInfo, Room
from Appointment.utils.identity import get_participant
from utils.models.query import *
from utils.models.semester import Semester
from generic.models import User, YQPointRecord

# 定义常量
SUMMARY_YEAR = 2025
SUMMARY_SEM_START = datetime(SUMMARY_YEAR, 1, 19)
SUMMARY_SEM_END = datetime(SUMMARY_YEAR + 1, 1, 19)

LAST_YEAR_SUMMARY_START = datetime(SUMMARY_YEAR - 1, 1, 16)
LAST_YEAR_SUMMARY_END = datetime(SUMMARY_YEAR, 1, 18)

# 硬编码三类房间的列表 Rid，包括自习室、研讨室、功能房
study_room_list = ['B108', 'B112', 'B118', 'B106', 'B119', 'B114']
talk_room_list = ['B104', 'B107A', 'B107B', 'B111', 'B206', 'R113', 'R201']
func_room_list = ['B217', 'B220', 'B221', 'B207',
                  'B208', 'B214', 'B206', 'B216', 'B111', 'B104']

# 本年度书院课「课程 id -> 选中人数/预选人数 比例」缓存，在 handle 中先调用 cal_select_course_ratio() 写入
_select_course_ratio_cache = None
# 本年度书院课「课程 id -> {preselect_count, success_count}」缓存
_course_stats_cache = None

# 所有用户「用户名 -> 刷卡或预约总天数」缓存，在处理个人数据时收集
_underground_usage_days_cache = {}

# 所有用户「用户名 -> 个人刷卡次数最多的自习室」缓存，在处理个人数据时收集
_study_room_top_cache = {}

# 所有用户「用户名 -> 最多学时书院课」缓存，在处理个人数据时收集
_most_hours_course_cache = {}

# 功能性函数


def datetime_converter(o):
    """供 json.dump 序列化 datetime/time/date 使用"""
    if isinstance(o, (datetime, time, date)):
        return o.isoformat()
    raise TypeError(
        f'Object of type {type(o).__name__} is not JSON serializable')


# 定义子模块数据处理函数(个人信息部分)

def get_user_register_date_and_days(user: 'User|NaturalPerson'):
    """
    获取用户账号注册日期和注册天数。
    返回: (注册日期, 注册天数) 或 None
    """
    if isinstance(user, User):
        person = NaturalPerson.objects.get_by_user(user)
    else:
        person = user

    if person is None:
        return None

    user_obj = person.get_user()
    if user_obj is None:
        return None

    date_joined = user_obj.date_joined
    days = (SUMMARY_SEM_END - date_joined).days
    return {
        'date_joined': date_joined.strftime('%Y-%m-%d'),
        'days': days,
    }

# 个人地下室使用总览

# 个人有刷卡或预约记录的总天数


def get_person_underground_usage(person: 'NaturalPerson'):
    """
    获取个人有刷卡或预约记录的总天数（去重后的日期数）。
    """
    user = person.get_user()
    if user is None:
        return 0

    card_dates = set(
        CardCheckInfo.objects.filter(
            Cardstudent__Sid=user,
            Cardtime__gt=SUMMARY_SEM_START,
            Cardtime__lt=SUMMARY_SEM_END
        ).values_list('Cardtime__date', flat=True).distinct()
    )
    if user is None:
        appoint_dates = set()
    else:
        appoint_dates = set(
            Appoint.objects.filter(
                students__Sid=user,
                Astart__gt=SUMMARY_SEM_START,
                Astart__lt=SUMMARY_SEM_END
            ).values_list('Astart__date', flat=True).distinct()
        )
    return len(card_dates | appoint_dates)

# 个人本年度首条刷卡/预约记录：日期、房间号、预约关键词（如有）


def get_person_first_underground_record(person: 'NaturalPerson'):
    """
    获取个人本年度首条刷卡/预约记录。
    对比第一条刷卡记录和第一条预约记录，返回时间更早的记录。
    返回: {'date': 日期, 'room': 房间号, 'usage': 预约关键词} 或 None
    """
    user = person.get_user()
    if user is None:
        card_record = None
    else:
        card_record = CardCheckInfo.objects.filter(
            Cardstudent__Sid=user,
            Cardtime__gt=SUMMARY_SEM_START,
            Cardtime__lt=SUMMARY_SEM_END
        ).select_related('Cardroom').order_by('Cardtime').first()

    user = person.get_user()
    if user is None:
        appoint_record = None
    else:
        appoint_record = Appoint.objects.filter(
            students__Sid=user,
            Astart__gt=SUMMARY_SEM_START,
            Astart__lt=SUMMARY_SEM_END
        ).select_related('Room').order_by('Astart').first()

    if card_record is None and appoint_record is None:
        return None

    if card_record is None:
        if appoint_record and appoint_record.Room:
            return {
                'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
                'room': appoint_record.Room.Rid,
                'usage': appoint_record.Ausage or '',
            }
        elif appoint_record:
            return {
                'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
                'room': None,
                'usage': appoint_record.Ausage or '',
            }
        return None

    if appoint_record is None:
        if card_record.Cardroom:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': card_record.Cardroom.Rid,
                'usage': '',
            }
        else:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': None,
                'usage': '',
            }

    if card_record.Cardtime < appoint_record.Astart:
        if card_record.Cardroom:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': card_record.Cardroom.Rid,
                'usage': '',
            }
        else:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': None,
                'usage': '',
            }

    if appoint_record.Room:
        return {
            'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
            'room': appoint_record.Room.Rid,
            'usage': appoint_record.Ausage or '',
        }
    else:
        return {
            'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
            'room': None,
            'usage': appoint_record.Ausage or '',
        }

# 3.个人本年度末条刷卡/预约记录：日期、房间号、预约关键词（如有）


def get_person_last_underground_record(person: 'NaturalPerson'):
    """
    获取个人本年度末条刷卡/预约记录。
    对比最后一条刷卡记录和最后一条预约记录，返回时间更晚的记录。
    返回: {'date': 日期, 'room': 房间号, 'usage': 预约关键词} 或 None
    """
    user = person.get_user()
    if user is None:
        card_record = None
    else:
        card_record = CardCheckInfo.objects.filter(
            Cardstudent__Sid=user,
            Cardtime__gt=SUMMARY_SEM_START,
            Cardtime__lt=SUMMARY_SEM_END
        ).select_related('Cardroom').order_by('-Cardtime').first()

    user = person.get_user()
    if user is None:
        appoint_record = None
    else:
        appoint_record = Appoint.objects.filter(
            students__Sid=user,
            Astart__gt=SUMMARY_SEM_START,
            Astart__lt=SUMMARY_SEM_END
        ).select_related('Room').order_by('-Astart').first()

    if card_record is None and appoint_record is None:
        return None

    if card_record is None:
        if appoint_record and appoint_record.Room:
            return {
                'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
                'room': appoint_record.Room.Rid,
                'usage': appoint_record.Ausage or '',
            }
        elif appoint_record:
            return {
                'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
                'room': None,
                'usage': appoint_record.Ausage or '',
            }
        return None

    if appoint_record is None:
        if card_record.Cardroom:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': card_record.Cardroom.Rid,
                'usage': '',
            }
        else:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': None,
                'usage': '',
            }

    if card_record.Cardtime > appoint_record.Astart:
        if card_record.Cardroom:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': card_record.Cardroom.Rid,
                'usage': '',
            }
        else:
            return {
                'date': card_record.Cardtime.strftime('%Y年%m月%d日'),
                'room': None,
                'usage': '',
            }

    if appoint_record.Room:
        return {
            'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
            'room': appoint_record.Room.Rid,
            'usage': appoint_record.Ausage or '',
        }
    else:
        return {
            'date': appoint_record.Astart.strftime('%Y年%m月%d日'),
            'room': None,
            'usage': appoint_record.Ausage or '',
        }

# 个人最长连续刷卡/预约天数，起止日期


def get_person_longest_underground_usage(person: 'NaturalPerson'):
    """
    获取个人最长连续刷卡/预约天数及起止日期。
    获取所有记录，按日期遍历，记录连续天数，如果中断则重置。
    """
    # 获取所有记录日期（去重）
    user = person.get_user()
    if user is None:
        card_dates = set()
    else:
        card_dates = set(
            CardCheckInfo.objects.filter(
                Cardstudent__Sid=user,
                Cardtime__gt=SUMMARY_SEM_START,
                Cardtime__lt=SUMMARY_SEM_END
            ).values_list('Cardtime__date', flat=True).distinct()
        )
    if user is None:
        appoint_dates = set()
    else:
        appoint_dates = set(
            Appoint.objects.filter(
                students__Sid=user,
                Astart__gt=SUMMARY_SEM_START,
                Astart__lt=SUMMARY_SEM_END
            ).values_list('Astart__date', flat=True).distinct()
        )
    all_dates = sorted(card_dates | appoint_dates)

    if not all_dates:
        return {
            'longest_continuous_days': 0,
            'longest_continuous_start_date': None,
            'longest_continuous_end_date': None,
        }

    longest_continuous_days = 0
    longest_continuous_start_date = None
    longest_continuous_end_date = None
    current_continuous_days = 0
    current_continuous_start_date = None
    previous_date = None

    for current_date in all_dates:
        if previous_date is None:
            # 第一条记录
            current_continuous_days = 1
            current_continuous_start_date = current_date
        elif (current_date - previous_date).days == 1:
            # 连续日期
            current_continuous_days += 1
        else:
            # 中断，重置
            current_continuous_days = 1
            current_continuous_start_date = current_date

        current_continuous_end_date = current_date

        if current_continuous_days > longest_continuous_days:
            longest_continuous_days = current_continuous_days
            longest_continuous_start_date = current_continuous_start_date
            longest_continuous_end_date = current_continuous_end_date

        previous_date = current_date

    return {
        'longest_continuous_days': longest_continuous_days,
        'longest_continuous_start_date': longest_continuous_start_date.strftime('%Y-%m-%d') if longest_continuous_start_date else None,
        'longest_continuous_end_date': longest_continuous_end_date.strftime('%Y-%m-%d') if longest_continuous_end_date else None,
    }

# 自习室部分统计


def get_person_study_room_usage(person: 'NaturalPerson'):
    """
    统计个人自习室使用情况：
    - 本年度自习室刷卡总次数
    - 刷卡次数最多的自习室及次数（次数相同则返回最早的房间号）
    - 去年刷卡次数最多的自习室及次数
    - 两者是否相同
    """
    # 获取个人本年度自习室刷卡总次数
    user = person.get_user()
    if user is None:
        study_room_num = 0
        study_room_dict = {}
    else:
        study_room_num = CardCheckInfo.objects.filter(
            Cardstudent__Sid=user,
            Cardroom__Rid__in=study_room_list,
            Cardtime__gt=SUMMARY_SEM_START,
            Cardtime__lt=SUMMARY_SEM_END
        ).count()

        # 分自习室房间号统计，返回字典（房间号: 刷卡次数）
        study_room_dict = defaultdict(int)
        for record in CardCheckInfo.objects.filter(
                Cardstudent__Sid=user,
                Cardroom__Rid__in=study_room_list,
                Cardtime__gt=SUMMARY_SEM_START,
                Cardtime__lt=SUMMARY_SEM_END).select_related('Cardroom'):
            if record.Cardroom:
                study_room_dict[record.Cardroom.Rid] += 1

    if study_room_dict:
        study_room_top, study_room_top_num = max(
            study_room_dict.items(), key=lambda x: (x[1], -ord(x[0][0]) if x[0] else 0))
    else:
        study_room_top, study_room_top_num = None, 0

    # 获取去年刷卡次数最多的自习室
    user = person.get_user()
    last_year_study_room_dict = defaultdict(int)
    if user is not None:
        for record in CardCheckInfo.objects.filter(
                Cardstudent__Sid=user,
                Cardroom__Rid__in=study_room_list,
                Cardtime__gt=LAST_YEAR_SUMMARY_START,
                Cardtime__lt=LAST_YEAR_SUMMARY_END).select_related('Cardroom'):
            if record.Cardroom:
                last_year_study_room_dict[record.Cardroom.Rid] += 1

    if last_year_study_room_dict:
        last_year_study_room_top, last_year_study_room_top_num = max(
            last_year_study_room_dict.items(), key=lambda x: (x[1], -ord(x[0][0]) if x[0] else 0))
    else:
        last_year_study_room_top, last_year_study_room_top_num = None, 0

    return {
        'study_room_num': study_room_num,
        'study_room_top': study_room_top,
        'study_room_top_num': study_room_top_num,
        'last_year_study_room_top': last_year_study_room_top,
        'last_year_study_room_top_num': last_year_study_room_top_num,
        'is_same_as_last_year': study_room_top == last_year_study_room_top,
    }

# 统计个人使用研讨室&功能房总次数


def get_person_talk_and_func_room_usage(person: 'NaturalPerson'):
    """
    统计个人研讨室和功能房使用情况：
    - 研讨室预约总次数、总时长、平均参与人数
    - 功能房预约总次数、总时长
    - 预约时长最长的一次记录（日期、房间号、时长、预约关键词）
    """
    # 1. 获取个人本年度研讨室预约总次数
    user = person.get_user()
    if user is None:
        talk_room_num = 0
        talk_room_hour = 0.0
        talk_room_average_participant_num = 0
        func_room_num = 0
        func_room_hour = 0.0
        all_room_appoints = Appoint.objects.none()
    else:
        talk_room_appoints = Appoint.objects.filter(
            students__Sid=user,
            Room__Rid__in=talk_room_list,
            Astart__gt=SUMMARY_SEM_START,
            Astart__lt=SUMMARY_SEM_END
        )
        talk_room_num = talk_room_appoints.count()

        # 2. 计算个人本年度研讨室预约总时长（单位：小时，保留一位小数）
        talk_room_durations = [
            (finish - start).total_seconds()
            for start, finish in talk_room_appoints.values_list('Astart', 'Afinish')
        ]
        talk_room_hour = round(sum(talk_room_durations) /
                               3600.0, 1) if talk_room_durations else 0.0

        # 3. 计算个人预约研讨室的平均参与人数（默认为0）
        # 使用 Count 统计每个预约的参与者数量，然后计算平均值
        talk_room_with_count = talk_room_appoints.annotate(
            participant_count=Count('students')
        )
        participant_counts = [
            a.participant_count for a in talk_room_with_count]
        talk_room_average_participant_num = round(
            sum(participant_counts) / len(participant_counts), 1) if participant_counts else 0

        # 4. 个人功能房预约总次数
        func_room_appoints = Appoint.objects.filter(
            students__Sid=user,
            Room__Rid__in=func_room_list,
            Astart__gt=SUMMARY_SEM_START,
            Astart__lt=SUMMARY_SEM_END
        )
        func_room_num = func_room_appoints.count()

        # 5. 计算个人本年度功能房预约总时长（单位：小时，保留一位小数）
        func_room_durations = [
            (finish - start).total_seconds()
            for start, finish in func_room_appoints.values_list('Astart', 'Afinish')
        ]
        func_room_hour = round(sum(func_room_durations) /
                               3600.0, 1) if func_room_durations else 0.0

        # 6. 找出本年度预约中时长最长的一次预约记录
        all_room_appoints = Appoint.objects.filter(
            students__Sid=user,
            Room__Rid__in=talk_room_list + func_room_list,
            Astart__gt=SUMMARY_SEM_START,
            Astart__lt=SUMMARY_SEM_END
        ).select_related('Room')

        talk_and_func_room_longest_record = None
        longest_duration = timedelta(0)
        for appoint in all_room_appoints:
            duration = appoint.Afinish - appoint.Astart
            if duration > longest_duration:
                longest_duration = duration
                talk_and_func_room_longest_record = appoint

    longest_record_info = None
    if talk_and_func_room_longest_record:
        longest_record_info = {
            'date': talk_and_func_room_longest_record.Astart.strftime('%Y年%m月%d日'),
            'room': talk_and_func_room_longest_record.Room.Rid if talk_and_func_room_longest_record.Room else None,
            'hour': round(longest_duration.total_seconds() / 3600.0, 1),
            'usage': talk_and_func_room_longest_record.Ausage or '',
        }

    return {
        'talk_room_num': talk_room_num,
        'talk_room_hour': talk_room_hour,
        'talk_room_average_participant_num': round(talk_room_average_participant_num, 1) if talk_room_average_participant_num else 0,
        'func_room_num': func_room_num,
        'func_room_hour': func_room_hour,
        'talk_and_func_room_longest_record': longest_record_info,
    }

# 预约习惯统计部分


def get_person_appoint_habit(person: 'NaturalPerson'):
    """
    1. 申请（创建）时间到开始时间的时间差：平均差值（小时）、最大差值、最大差值对应记录（日期、房间号、预约关键词）
    2. 按房间号统计个人预约次数最多的房间号，返回房间号、次数
    3. 按类别统计当天预约与临时预约次数；当天预约中最小时间差及对应记录（日期、房间号、预约关键词）
    """
    user = person.get_user()
    if user is None:
        appoint_list = []
        n = 0
    else:
        appoint_records = Appoint.objects.filter(
            students__Sid=user,
            Astart__gt=SUMMARY_SEM_START,
            Astart__lt=SUMMARY_SEM_END,
        ).select_related('Room')
        appoint_list = list(appoint_records)
        n = len(appoint_list)

    if n == 0:
        return {
            'average_diff': None,
            'max_diff': None,
            'max_diff_record': None,
            'room_num_top': None,
            'room_num_top_num': None,
            'day_appoint_num': 0,
            'temporary_appoint_num': 0,
            'day_appoint_min_diff': None,
            'day_appoint_min_diff_record': None,
        }

    # 1. 申请到开始的时间差：平均（小时）、最大（小时）、最大差值对应的一条记录
    create_start_list = [(r.Atime, r.Astart) for r in appoint_list]
    diffs_seconds = [(start - create).total_seconds()
                     for create, start in create_start_list]
    average_diff = round(sum(diffs_seconds) / 3600.0 / n, 1)
    max_diff_seconds = max(diffs_seconds)
    max_diff_hours = round(max_diff_seconds / 3600.0, 1)
    max_diff_idx = diffs_seconds.index(max_diff_seconds)
    max_diff_record_obj = appoint_list[max_diff_idx]
    max_diff_record = {
        'date': max_diff_record_obj.Astart.strftime('%Y年%m月%d日'),
        'room': max_diff_record_obj.Room.Rid if max_diff_record_obj.Room else None,
        'usage': max_diff_record_obj.Ausage,
    }

    # 2. 按房间号统计，预约次数最多的房间号及次数
    room_num_dict = defaultdict(int)
    for r in appoint_list:
        if r.Room:
            room_num_dict[r.Room.Rid] += 1
    room_num_top, room_num_top_num = max(
        room_num_dict.items(), key=lambda x: x[1])

    # 3. 当天预约 / 临时预约次数；当天预约中最小时间差及对应记录
    day_appoint_num = sum(
        1 for r in appoint_list if r.Atype == Appoint.Type.TODAY)
    temporary_appoint_num = sum(
        1 for r in appoint_list if r.Atype == Appoint.Type.TEMPORARY)
    day_appoints = [r for r in appoint_list if r.Atype == Appoint.Type.TODAY]
    if day_appoints:
        day_diffs = [(r.Astart - r.Atime).total_seconds()
                     for r in day_appoints]
        day_appoint_min_diff_seconds = min(day_diffs)
        day_appoint_min_diff = round(day_appoint_min_diff_seconds / 3600.0, 1)
        day_min_record_obj = day_appoints[day_diffs.index(
            day_appoint_min_diff_seconds)]
        day_appoint_min_diff_record = {
            'date': day_min_record_obj.Astart.strftime('%Y年%m月%d日'),
            'room': day_min_record_obj.Room.Rid if day_min_record_obj.Room else None,
            'usage': day_min_record_obj.Ausage,
        }
    else:
        day_appoint_min_diff = None
        day_appoint_min_diff_record = None

    return {
        'average_diff': average_diff,
        'max_diff': max_diff_hours,
        'max_diff_record': max_diff_record,
        'room_num_top': room_num_top,
        'room_num_top_num': room_num_top_num,
        'day_appoint_num': day_appoint_num,
        'temporary_appoint_num': temporary_appoint_num,
        'day_appoint_min_diff': day_appoint_min_diff,
        'day_appoint_min_diff_record': day_appoint_min_diff_record,
    }


def get_person_login_days(person: 'NaturalPerson'):
    """
    获取个人年度登录总天数（去重后的日期数）。
    """
    user = person.get_user()
    if user is None:
        return 0

    login_dates = YQPointRecord.objects.filter(
        user=user,
        source_type=YQPointRecord.SourceType.CHECK_IN,
        time__gt=SUMMARY_SEM_START,
        time__lt=SUMMARY_SEM_END
    ).values_list('time__date', flat=True).distinct()

    return len(set(login_dates))

# 处理小组相关内容


def get_person_org_usage(person: 'NaturalPerson'):
    """
    统计个人小组和活动参与情况：
    - 本年度参与的小组总数和名称列表
    - 参加小组活动的次数和累计时长
    - 参与次数最多的小组及次数
    - 开始时间最早/最晚的活动（仅比较小时和分钟）
    - 参与次数最多的时段窗口
    """
    # 获取个人本年度参与的小组总数（2024春、2025秋，包括全年类型）
    org_num = Position.objects.filter(
        person=person,
        year=2024,
        semester__in=[Semester.SPRING, Semester.ANNUAL]
    ).count() + Position.objects.filter(
        person=person,
        year=2025,
        semester__in=[Semester.FALL, Semester.ANNUAL]
    ).count()

    # 获取这些小组的名称
    org_name_list = list(
        Position.objects.filter(
            person=person,
            year=2024,
            semester=Semester.SPRING
        ).values_list('org__oname', flat=True)
    ) + list(
        Position.objects.filter(
            person=person,
            year=2025,
            semester__in=[Semester.FALL, Semester.ANNUAL]
        ).values_list('org__oname', flat=True)
    )

    # 筛选出时间段内所有的该用户的 Participation 记录（状态必须是已参与）
    participation_records = Participation.objects.filter(
        person=person,
        status=Participation.AttendStatus.ATTENDED,
        activity__start__gt=SUMMARY_SEM_START,
        activity__start__lt=SUMMARY_SEM_END
    ).select_related('activity__organization_id', 'activity')

    # 统计参加小组活动的次数和累计时长
    act_num = participation_records.count()
    act_durations = [
        (finish - start).total_seconds()
        for start, finish in participation_records.values_list('activity__start', 'activity__end')
    ]
    act_hour = round(sum(act_durations) / 3600.0, 1) if act_durations else 0.0

    # 统计每个小组的参与次数
    org_num_dict = defaultdict(int)
    for record in participation_records:
        if record.activity and record.activity.organization_id:
            org_num_dict[record.activity.organization_id.oname] += 1

    # 找出次数最多的小组（次数相同则返回最早的小组名）
    if org_num_dict:
        org_top, org_top_num = max(
            org_num_dict.items(), key=lambda x: (x[1], x[0]))
    else:
        org_top, org_top_num = None, 0

    # 找出开始时间最早的活动（仅比较小时和分钟）
    earliest_act_info = None
    earliest_act_time = None
    for record in participation_records:
        if record.activity:
            act_time = record.activity.start.time()
            if earliest_act_time is None or act_time < earliest_act_time:
                earliest_act_time = act_time
                earliest_act_info = {
                    'date': record.activity.start.strftime('%Y年%m月%d日'),
                    'name': record.activity.title or '',
                    'time': act_time.strftime('%H:%M'),
                }

    # 找出开始时间最晚的活动（仅比较小时和分钟）
    latest_act_info = None
    latest_act_time = None
    for record in participation_records:
        if record.activity:
            act_time = record.activity.start.time()
            if latest_act_time is None or act_time > latest_act_time:
                latest_act_time = act_time
                latest_act_info = {
                    'date': record.activity.start.strftime('%Y年%m月%d日'),
                    'name': record.activity.title or '',
                    'time': act_time.strftime('%H:%M'),
                }

    # 统计每个时段窗口（小时）的参与次数
    window_num_dict = defaultdict(int)
    for record in participation_records:
        if record.activity:
            hour = record.activity.start.hour
            if 6 <= hour <= 23:
                window_num_dict[hour] += 1

    # 找出次数最多的窗口（次数相同则返回最早的窗口）
    if window_num_dict:
        window_top, window_top_num = max(
            window_num_dict.items(), key=lambda x: (x[1], x[0]))
    else:
        window_top, window_top_num = None, 0

    return {
        'org_num': org_num,
        'org_name_list': org_name_list,
        'act_num': act_num,
        'act_hour': act_hour,
        'org_top': org_top,
        'org_top_num': org_top_num,
        'earliest_act_record': earliest_act_info,
        'latest_act_record': latest_act_info,
        'window_top': window_top,
        'window_top_num': window_top_num,
    }

# 统计用户书院课程参与情况


def get_person_course_usage(person: 'NaturalPerson'):
    # 获取用户所有（不止本年度）有学时记录的课程总数
    course_num = CourseRecord.objects.filter(
        person=person,
        total_hours__gt=0).count()
    # 获取用户所有（不止本年度）的总有效学时数
    valid_hours = CourseRecord.objects.filter(
        person=person,
        total_hours__gt=0).aggregate(
        valid_hours=Sum('total_hours'))['valid_hours'] or 0

    # 然后五种类型分别统计有无（使用Course.CourseType.values中的值作为键，值为bool flag），遍历用户的学时表以更新键值对，最后，flag为True的类型对应的文字加到字符串中，不能重复加，最后返回字符串
    valid_hours_dict = defaultdict(bool)
    for record in CourseRecord.objects.filter(
            person=person,
            total_hours__gt=0).select_related('course'):
        if record.course and record.course.type is not None:
            valid_hours_dict[record.course.type] = True
    course_type_str = ''
    for course_type in Course.CourseType:
        if valid_hours_dict[course_type.value]:
            course_type_str += course_type.label + ' '
    # 从所有有效学时中找到最多的学时数对应的课程，返回课程名称、学时数，若有多个课程学时数相同，则返回最早的课程
    most_hours_course = None
    most_hours = 0
    for record in CourseRecord.objects.filter(
            person=person,
            total_hours__gt=0):
        if record.total_hours > most_hours:
            most_hours = record.total_hours
            most_hours_course = record.course
    # 从用户本年度（24春、25秋）所成功选课的书院课中，找出成功人数/总选课人数比例最低的课程；比例相同则返回最后更新的课程（id 最大）
    ratio_by_course = _get_select_course_ratio()
    course_stats = _get_course_stats()  # 获取课程统计信息（包含总选课人数）
    person_course_statuses = [
        CourseParticipant.Status.SUCCESS
    ]
    person_annual_courses = list(
        Course.objects.exclude(status=Course.Status.ABORT)
        .filter(
            Q(year=2024, semester=Semester.SPRING)
            | Q(year=2025, semester=Semester.FALL)
        )
        .filter(
            participant_set__person=person,
            participant_set__status__in=person_course_statuses,
        )
        .distinct()
        .order_by('-id')  # 按id倒序，id大的（最后更新的）在前面
    )
    lowest_ratio_course = None
    lowest_ratio = float('inf')  # 初始化为无穷大，这样任何比例都会更小
    for course in person_annual_courses:
        r = ratio_by_course.get(course.id, 0)
        # 如果比例更小，则更新（因为已经按id倒序排列，比例相同时第一个就是id最大的）
        if r < lowest_ratio:
            lowest_ratio = r
            lowest_ratio_course = course
    highest_ratio_course_info = None
    if lowest_ratio_course is not None:
        stats = course_stats.get(lowest_ratio_course.id, {})
        total_participants = stats.get('preselect_count', 0)
        highest_ratio_course_info = {
            'name': lowest_ratio_course.name,
            'total_participants': total_participants,
        }

    return {
        'course_num': course_num,
        'valid_hours': valid_hours,
        'course_type_str': course_type_str.strip(),
        'most_hours_course': most_hours_course.name if most_hours_course else None,
        'most_hours': most_hours,
        'highest_ratio_course': highest_ratio_course_info,
    }

# 统计用户年度元气值收入总额


def get_person_yqpoint_income(person: 'NaturalPerson'):
    """
    获取用户本年度元气值收入总额（签到获得的元气值）。
    """
    user = person.get_user()
    if user is None:
        return 0

    result = YQPointRecord.objects.filter(
        user=user,
        source_type=YQPointRecord.SourceType.CHECK_IN,
        time__gt=SUMMARY_SEM_START,
        time__lt=SUMMARY_SEM_END
    ).aggregate(total_income=Sum('delta'))

    return result['total_income'] or 0

# 定义子模块数据处理函数(排名部分)（与其他用户对比的部分都放这个里面）

# 定义子模块数据处理函数(排名部分)


def calculate_underground_usage_percentile():
    """
    计算每个用户有刷卡或预约记录的总天数超越其他用户的百分比。
    使用预缓存的 _underground_usage_days_cache 数据。
    返回: {username: percentile} 字典，percentile 为 0-100 的浮点数，表示超越了多少百分比的其他用户。
    """
    global _underground_usage_days_cache

    if not _underground_usage_days_cache:
        return {}

    # 将所有用户按天数排序（从低到高）
    sorted_users = sorted(
        _underground_usage_days_cache.items(), key=lambda x: x[1])
    total_users = len(sorted_users)

    if total_users == 0:
        return {}

    # 计算每个用户的百分比排名
    # percentile = (小于该用户天数的用户数) / 总用户数 * 100
    result = {}

    # 使用字典记录每个天数对应的用户列表（处理相同天数的情况）
    days_to_users = defaultdict(list)
    for username, days in sorted_users:
        days_to_users[days].append(username)

    # 计算每个用户的百分比
    users_below = 0  # 当前天数以下的用户数
    for days in sorted(set(_underground_usage_days_cache.values())):
        users_with_this_days = days_to_users[days]
        # 对于相同天数的用户，使用相同的百分比（取中位数）
        # 百分比 = (users_below + users_with_this_days - 1) / total_users * 100
        percentile = (users_below / total_users) * \
            100 if total_users > 1 else 0

        for username in users_with_this_days:
            result[username] = round(percentile, 2)

        users_below += len(users_with_this_days)

    return result

# 计算每个用户的 本年度“个人刷卡天数最多的自习室”记录相同的用户数


def calculate_same_study_room_top_count():
    """
    计算每个用户的"本年度个人刷卡次数最多的自习室"记录相同的用户数。
    使用预缓存的 _study_room_top_cache 数据。
    先按自习室统计用户数（自习室 -> 用户列表），再遍历用户计算相同用户数。
    返回: {username: count} 字典，count 为选择相同自习室的其他用户数（不包括自己）。
    """
    global _study_room_top_cache

    if not _study_room_top_cache:
        return {}

    # 按自习室统计用户数：自习室 -> 用户列表
    room_to_users = defaultdict(list)
    for username, room in _study_room_top_cache.items():
        if room is not None:  # 只统计有自习室记录的用户
            room_to_users[room].append(username)

    # 计算每个用户有多少其他用户选择了相同的自习室
    result = {}
    for username, room in _study_room_top_cache.items():
        if room is None:
            # 如果没有自习室记录，相同用户数为0
            result[username] = 0
        else:
            # 相同自习室的用户数 - 1（排除自己）
            same_room_users = room_to_users[room]
            result[username] = len(same_room_users) - 1

    return result

# 计算每个用户的 “最多学时书院课” 与自己相同的用户数


def calculate_same_most_hours_course_count():
    """
    计算每个用户的"最多学时书院课"与自己相同的用户数。
    使用预缓存的 _most_hours_course_cache 数据。
    先按课程名统计用户数（课程名 -> 用户列表），再遍历用户计算相同用户数。
    返回: {username: count} 字典，count 为选择相同课程的其他用户数（不包括自己）。
    """
    global _most_hours_course_cache

    if not _most_hours_course_cache:
        return {}

    # 按课程名统计用户数：课程名 -> 用户列表
    course_to_users = defaultdict(list)
    for username, course_name in _most_hours_course_cache.items():
        if course_name is not None:  # 只统计有课程记录的用户
            course_to_users[course_name].append(username)

    # 计算每个用户有多少其他用户选择了相同的课程
    result = {}
    for username, course_name in _most_hours_course_cache.items():
        if course_name is None:
            # 如果没有课程记录，相同用户数为0
            result[username] = 0
        else:
            # 相同课程的用户数 - 1（排除自己）
            same_course_users = course_to_users[course_name]
            result[username] = len(same_course_users) - 1

    return result

# 计算 a.个人账号预约中，最经常一起预约的人、一起预约次数
#      b.小组账号预约中，最经常一起预约的人、一起预约次数
# 方法：先取出时间段内所有的预约记录，根据预约申请者的类型判断是个人账户预约还是小组账户预约，然后对于每个参加本次预约的用户，遍历除了自己以外的其他参与者来更新自己的键值对表
# 每个用户分别维护一系列键值对，记录其他人和自己一起出现在预约中的次数，最后对每个用户的键值对表排序得到结果


def calculate_most_frequent_co_appoint():
    """
    计算每个用户最经常一起预约的人和一起预约次数。
    分别统计个人账号预约和小组账号预约两种情况。

    方法：
    1. 获取时间段内所有预约记录
    2. 根据预约申请者(major_student.Sid.utype)判断是个人账户预约还是小组账户预约：utype == Type.ORG 算作小组预约，其他一律算作个人预约
    3. 对于每个参与者，遍历除了自己以外的其他参与者来更新自己的键值对表
    4. 每个用户分别维护键值对，记录其他人和自己一起出现在预约中的次数
    5. 对每个用户的键值对表排序得到结果

    返回: {
        'personal': {username: {'co_name': 自然人姓名, 'count': 次数}},
        'organization': {username: {'co_name': 自然人姓名, 'count': 次数}}
    }
    """
    # 获取时间段内所有预约记录
    appoints = Appoint.objects.filter(
        Astart__gt=SUMMARY_SEM_START,
        Astart__lt=SUMMARY_SEM_END
    ).select_related('major_student__Sid').prefetch_related('students__Sid')

    # 个人账户预约：用户 -> {其他用户: 一起预约次数}
    personal_co_appoint_dict = defaultdict(lambda: defaultdict(int))
    # 小组账户预约：用户 -> {其他用户: 一起预约次数}
    org_co_appoint_dict = defaultdict(lambda: defaultdict(int))

    # 建立username到name的映射缓存
    username_to_name_cache = {}

    for appoint in appoints:
        # 判断是个人账户预约还是小组账户预约
        if appoint.major_student is None:
            continue

        appointer_user = appoint.major_student.Sid
        if appointer_user is None:
            continue

        # utype == Type.ORG 算作小组预约，其他一律算作个人预约
        is_personal = appointer_user.utype != User.Type.ORG

        # 获取所有参与者
        participants = appoint.students.all()
        participant_usernames = []
        for participant in participants:
            if participant.Sid is not None:
                username = participant.Sid.username
                participant_usernames.append(username)
                # 缓存username到name的映射
                if username not in username_to_name_cache:
                    try:
                        person = NaturalPerson.objects.get_by_user(
                            participant.Sid)
                        username_to_name_cache[username] = person.name
                    except NaturalPerson.DoesNotExist:
                        # 如果不是自然人，使用User的name字段
                        username_to_name_cache[username] = participant.Sid.name or username

        # 对于每个参与者，遍历除了自己以外的其他参与者
        for username in participant_usernames:
            co_appoint_dict = personal_co_appoint_dict if is_personal else org_co_appoint_dict

            for co_username in participant_usernames:
                if co_username != username:
                    co_appoint_dict[username][co_username] += 1

    # 对每个用户的键值对表排序，得到最经常一起预约的人和次数
    result_personal = {}
    result_org = {}

    for username, co_dict in personal_co_appoint_dict.items():
        if co_dict:
            # 按次数排序，次数相同则按用户名排序
            sorted_co = sorted(co_dict.items(), key=lambda x: (-x[1], x[0]))
            co_username, count = sorted_co[0]
            # 获取对应的自然人姓名
            co_name = username_to_name_cache.get(co_username, co_username)
            result_personal[username] = {
                'co_name': co_name,
                'count': count,
            }
        else:
            result_personal[username] = {
                'co_name': None,
                'count': 0,
            }

    for username, co_dict in org_co_appoint_dict.items():
        if co_dict:
            # 按次数排序，次数相同则按用户名排序
            sorted_co = sorted(co_dict.items(), key=lambda x: (-x[1], x[0]))
            co_username, count = sorted_co[0]
            # 获取对应的自然人姓名
            co_name = username_to_name_cache.get(co_username, co_username)
            result_org[username] = {
                'co_name': co_name,
                'count': count,
            }
        else:
            result_org[username] = {
                'co_name': None,
                'count': 0,
            }

    # 统计有数据的条目数
    personal_with_data = sum(1 for v in result_personal.values() if v.get('co_name') is not None and v.get('count', 0) > 0)
    org_with_data = sum(1 for v in result_org.values() if v.get('co_name') is not None and v.get('count', 0) > 0)
    
    import sys
    output = sys.stdout
    output.write(f"\n=== 共同预约统计调试信息 ===\n")
    output.write(f"有个人预约共同预约最多次数的条目数: {personal_with_data}\n")
    output.write(f"有小组共同预约最多次数的条目数: {org_with_data}\n")
    output.write(f"个人预约总条目数: {len(result_personal)}\n")
    output.write(f"小组预约总条目数: {len(result_org)}\n")
    output.write("=" * 50 + "\n\n")
    output.flush()

    return {
        'personal': result_personal,
        'organization': result_org,
    }


# 定义子模块数据处理函数(总统计数据部分)


# 地下室年度使用情况总览（自习室刷卡总次数，研讨室预约总次数，功能房预约总次数）


def get_underground_annual_usage():

    # 获取自习室刷卡总次数
    study_room_num = CardCheckInfo.objects.filter(
        Cardroom__Rid__in=study_room_list, Cardtime__gt=SUMMARY_SEM_START, Cardtime__lt=SUMMARY_SEM_END).count()
    # 获取研讨室预约总次数
    talk_room_num = Appoint.objects.filter(
        Room__Rid__in=talk_room_list, Astart__gt=SUMMARY_SEM_START, Astart__lt=SUMMARY_SEM_END).count()
    # 获取功能房预约总次数
    func_room_num = Appoint.objects.filter(
        Room__Rid__in=func_room_list, Astart__gt=SUMMARY_SEM_START, Astart__lt=SUMMARY_SEM_END).count()
    return {
        'study_room_num': study_room_num,
        'talk_room_num': talk_room_num,
        'func_room_num': func_room_num,
    }

# YPPF 年度使用情况总览（智慧书院现有小组总数，小组年度发起活动总次数，年度开设书院课程总数）


def get_yppf_annual_usage():
    # 获取智慧书院现有小组总数
    org_num = Organization.objects.activated().count()
    # 获取小组年度发起活动总次数
    act_num = Activity.objects.exclude(status__in=[Activity.Status.REVIEWING, Activity.Status.CANCELED, Activity.Status.ABORT, Activity.Status.REJECT]).filter(
        start__gt=SUMMARY_SEM_START, start__lt=SUMMARY_SEM_END).count()
    # 获取年度开设书院课程总数 （24学年春季，25学年秋季）
    course_num = Course.objects.exclude(status=Course.Status.ABORT).filter(year=2024, semester=Semester.SPRING).count(
    ) + Course.objects.exclude(status=Course.Status.ABORT).filter(year=2025, semester=Semester.FALL).count()

    return {
        'org_num': org_num,
        'act_num': act_num,
        'course_num': course_num,
    }


# 计算本年度所有书院课的选中人数/预选人数 比例，并返回课程-比例键值对
def cal_select_course_ratio():
    """本年度（24春、25秋）书院课：预选人数=SELECT/SUCCESS/FAILED，选中人数=SUCCESS；比例=选中/预选，预选为0则比例为0。返回 {course_id: ratio}。"""
    global _select_course_ratio_cache, _course_stats_cache
    preselect_statuses = [
        CourseParticipant.Status.SELECT,
        CourseParticipant.Status.SUCCESS,
        CourseParticipant.Status.FAILED,
    ]
    courses = Course.objects.exclude(status=Course.Status.ABORT).filter(
        Q(year=2024, semester=Semester.SPRING) | Q(
            year=2025, semester=Semester.FALL)
    ).annotate(
        preselect_count=Count(
            'participant_set',
            filter=Q(participant_set__status__in=preselect_statuses),
        ),
        success_count=Count(
            'participant_set',
            filter=Q(participant_set__status=CourseParticipant.Status.SUCCESS),
        ),
    )
    result = {}
    import sys
    output = sys.stdout
    output.write("\n=== 课程选课比例调试信息 ===\n")
    output.write(
        f"{'课程ID':<10} {'课程名称':<30} {'成功人数':<10} {'总选课人数':<12} {'比例':<10}\n")
    output.write("-" * 80 + "\n")
    for c in courses.order_by('id'):
        ratio = (c.success_count / c.preselect_count) if c.preselect_count else 0
        result[c.id] = round(ratio, 4)
        course_name = c.name[:28] if len(c.name) > 28 else c.name
        output.write(
            f"{c.id:<10} {course_name:<30} {c.success_count:<10} {c.preselect_count:<12} {ratio:.4f}\n")
    output.write(f"\n总计: {len(result)} 门课程\n")
    output.write("=" * 80 + "\n\n")
    output.flush()
    _select_course_ratio_cache = result
    # 同时更新统计信息缓存
    _course_stats_cache = {}
    for c in courses.order_by('id'):
        _course_stats_cache[c.id] = {
            'preselect_count': c.preselect_count,
            'success_count': c.success_count,
        }
    return result


def _get_select_course_ratio():
    """获取课程-比例缓存，未计算则先调用 cal_select_course_ratio()。"""
    global _select_course_ratio_cache
    if _select_course_ratio_cache is None:
        cal_select_course_ratio()
    return _select_course_ratio_cache


def _get_course_stats():
    """获取课程统计信息缓存（包含总选课人数和成功人数），未计算则先调用 cal_select_course_ratio()。"""
    global _course_stats_cache
    if _course_stats_cache is None:
        # 重新查询以获取统计信息
        preselect_statuses = [
            CourseParticipant.Status.SELECT,
            CourseParticipant.Status.SUCCESS,
            CourseParticipant.Status.FAILED,
        ]
        courses = Course.objects.exclude(status=Course.Status.ABORT).filter(
            Q(year=2024, semester=Semester.SPRING) | Q(
                year=2025, semester=Semester.FALL)
        ).annotate(
            preselect_count=Count(
                'participant_set',
                filter=Q(participant_set__status__in=preselect_statuses),
            ),
            success_count=Count(
                'participant_set',
                filter=Q(participant_set__status=CourseParticipant.Status.SUCCESS),
            ),
        )
        _course_stats_cache = {}
        for c in courses:
            _course_stats_cache[c.id] = {
                'preselect_count': c.preselect_count,
                'success_count': c.success_count,
            }
    return _course_stats_cache


# 定义命令处理函数


class Command(BaseCommand):
    help = '导出2025年度总结数据'

    def handle(self, *args, **option):

        # 总统计数据部分，写入到 raw_data/summary2025/summary_overall_2025.json 文件中

        import os
        os.makedirs('raw_data/summary2025', exist_ok=True)

        overall_info = get_underground_annual_usage()
        overall_info.update(get_yppf_annual_usage())
        with open('raw_data/summary2025/summary_overall_2025.json', 'w', encoding='utf-8') as f:
            json.dump(overall_info, f, default=datetime_converter,
                      ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(
            "总统计数据已写入: raw_data/summary2025/summary_overall_2025.json"))
        # ========== 预计算课程比例 ==========
        self.stdout.write("预计算本年度所有书院课的选中/预选比例...")
        cal_select_course_ratio()
        self.stdout.write(self.style.SUCCESS("课程比例计算完成"))
        # 个人信息部分，写入到 raw_data/summary2025/summary2025.json 文件中
        # 获取所有对应着 “自然人”/"老师”/“学生” 的“用户”账号
        # 依次获取每个人的数据，并写入到json文件中 （ raw_data/summary2025/ 目录下 summary2025.json 文件中）
        # ========== 个人信息部分 ==========
        self.stdout.write("开始导出个人信息数据...")
        # 初始化缓存
        global _underground_usage_days_cache, _study_room_top_cache, _most_hours_course_cache
        _underground_usage_days_cache = {}
        _study_room_top_cache = {}
        _most_hours_course_cache = {}

        person_data = {}
        user_count = 0

        users = User.objects.filter(utype__in=[
                                    User.Type.PERSON, User.Type.TEACHER, User.Type.STUDENT]).order_by('username')
        total_users = users.count()

        for user in users:
            try:
                person = NaturalPerson.objects.get_by_user(user)
            except NaturalPerson.DoesNotExist:
                continue

            user_count += 1
            if user_count % 100 == 0:
                self.stdout.write(f"已处理 {user_count}/{total_users} 个用户...")

            # 组装个人数据
            person_info = {}

            # 用户注册信息
            register_info = get_user_register_date_and_days(person)
            if register_info:
                person_info.update(register_info)

            # 地下室使用总览
            underground_usage_days = get_person_underground_usage(person)
            person_info['underground_usage_days'] = underground_usage_days
            # 缓存用户名和天数，用于后续排名计算
            _underground_usage_days_cache[user.username] = underground_usage_days

            person_info['first_underground_record'] = get_person_first_underground_record(
                person)
            person_info['last_underground_record'] = get_person_last_underground_record(
                person)
            person_info['longest_underground_usage'] = get_person_longest_underground_usage(
                person)

            # 自习室使用情况
            study_room_usage = get_person_study_room_usage(person)
            person_info['study_room_usage'] = study_room_usage
            # 缓存用户名和最多的自习室，用于后续排名计算
            _study_room_top_cache[user.username] = study_room_usage.get(
                'study_room_top')

            # 研讨室和功能房使用情况
            person_info['talk_and_func_room_usage'] = get_person_talk_and_func_room_usage(
                person)

            # 预约习惯
            person_info['appoint_habit'] = get_person_appoint_habit(person)

            # 登录天数
            person_info['login_days'] = get_person_login_days(person)

            # 小组和活动参与情况
            person_info['org_usage'] = get_person_org_usage(person)

            # 书院课程参与情况
            course_usage = get_person_course_usage(person)
            person_info['course_usage'] = course_usage
            # 缓存用户名和最多学时课程，用于后续排名计算
            _most_hours_course_cache[user.username] = course_usage.get(
                'most_hours_course')

            # 元气值收入
            person_info['yqpoint_income'] = get_person_yqpoint_income(person)

            # 添加自然人姓名
            person_info['name'] = person.name if person.name else ''

            # 使用用户名作为key
            person_data[user.username] = person_info

        # 写入个人信息JSON文件（按用户名排序）
        person_file = 'raw_data/summary2025/summary2025.json'
        # 确保按用户名排序
        sorted_person_data = dict(sorted(person_data.items()))
        with open(person_file, 'w', encoding='utf-8') as f:
            json.dump(sorted_person_data, f, default=datetime_converter,
                      ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(
            f"个人信息数据已写入: {person_file} (共 {user_count} 个用户)"))

        # ========== 排名数据部分 ==========
        self.stdout.write("开始计算排名数据...")
        rank_data = {}

        # 计算每个用户有刷卡或预约记录的总天数超越其他用户的百分比
        underground_percentile = calculate_underground_usage_percentile()

        # 计算每个用户的"个人刷卡次数最多的自习室"记录相同的用户数
        same_study_room_top_count = calculate_same_study_room_top_count()

        # 计算每个用户的"最多学时书院课"与自己相同的用户数
        same_most_hours_course_count = calculate_same_most_hours_course_count()

        # 计算每个用户最经常一起预约的人和一起预约次数（个人账户和小组账户分别统计）
        most_frequent_co_appoint = calculate_most_frequent_co_appoint()

        # 将数据组织为 用户名 -> 数据名 -> 值 的结构
        all_usernames = (
            set(underground_percentile.keys()) |
            set(same_study_room_top_count.keys()) |
            set(same_most_hours_course_count.keys()) |
            set(most_frequent_co_appoint['personal'].keys()) |
            set(most_frequent_co_appoint['organization'].keys())
        )

        for username in all_usernames:
            if username not in rank_data:
                rank_data[username] = {}

            if username in underground_percentile:
                rank_data[username]['underground_usage_percentile'] = underground_percentile[username]

            if username in same_study_room_top_count:
                rank_data[username]['same_study_room_top_count'] = same_study_room_top_count[username]

            if username in same_most_hours_course_count:
                rank_data[username]['same_most_hours_course_count'] = same_most_hours_course_count[username]

            # 个人账号预约中最经常一起预约的人
            if username in most_frequent_co_appoint['personal']:
                if username in most_frequent_co_appoint['personal']:
                    rank_data[username]['personal_most_frequent_co_appoint'] = most_frequent_co_appoint['personal'][username]

            # 小组账号预约中最经常一起预约的人
            if username in most_frequent_co_appoint['organization']:
                if username in most_frequent_co_appoint['organization']:
                    rank_data[username]['organization_most_frequent_co_appoint'] = most_frequent_co_appoint['organization'][username]

        # 按用户名排序
        sorted_rank_data = dict(sorted(rank_data.items()))

        rank_file = 'raw_data/summary2025/rank2025.json'
        with open(rank_file, 'w', encoding='utf-8') as f:
            json.dump(sorted_rank_data, f, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"排名数据已写入: {rank_file}"))

        self.stdout.write(self.style.SUCCESS("\n所有数据导出完成！"))
