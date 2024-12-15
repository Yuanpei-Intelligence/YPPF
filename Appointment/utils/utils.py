from datetime import timedelta

from django.http import HttpRequest
from django.db.models import Q, QuerySet

from Appointment.models import Room, Appoint

'''
YWolfeee:
utils.py中保存了一些比较杂碎的带有信息量的数据，例如对应表等。
微信消息的发送、日志的写入也在本文件中，使用前可以看一下代码的说明。
所有和scheduler无关、和互联网交互无关的工具函数，可以在本文件中实现。
'''

ip_room_dict = {
    "152": "B104",
    "155": "B104",
    "132": "B106",
    "153": "B106",
    "131": "B107A",
    "135": "B107B",
    "134": "B108",
    "151": "B108",
    "146": "B111",
    "149": "B111",
    "141": "B112",
    "148": "B112",
    # "138": "B114", # 不准 自习室
    "139": "B114",
    "144": "B118",
    "145": "B118",
    "140": "B119",
    "147": "B119",
    "129": "B205",
    "102": "B206",
    "106": "B206",
    "105": "B207",
    "107": "B207",
    "110": "B208",
    "111": "B208",
    "103": "B209",
    "108": "B209",
    "121": "B214",
    "128": "B214",  # 镜子 舞蹈室
    "119": "B215",
    "117": "B216",
    "124": "B216",  # 镜子 跑步机房
    "122": "B217",
    "126": "B217",
    "113": "B218",
    "120": "B220",
    "130": "B220",
    "112": "B221",  # 琴房 看不到门口谱子位置
    "123": "B221",  # 琴房 看不到小提琴位
    "118": "B222",
    "125": "B222",
}

door_room_dict = {
    "2020092016162884": "B104",
    "2020092016370963": "B106A",
    "2020092016422704": "B106B",
    "2020092016464351": "B107A",
    "2020092016550340": "B108A",
    "2020092017010542": "B108B",
    "2020092017070505": "B107B",
    "2020092017084647": "B000",  # 值班室
    "2020092017233640": "B112A",
    "2020092017234462": "B112B",
    "2020092017235201": "B111",
    "2020092017393941": "B114A",
    "2020092017475922": "B114B",
    "2020092017481264": "B118",
    "2020092017482150": "B119",
    "2020092018023538": "B218",
    "2020092018030345": "B220",
    "2020092018031303": "B221",
    "2020092018032470": "B222",
    "2020092018182960": "B214A",
    "2020092018184631": "B214B",
    "2020092018185928": "B216",
    "2020092018201454": "B217",
    "2020092018400410": "B209",
    "2020092018521223": "B205",
    "2020092018522586": "B206A",
    "2020092018523750": "B206B",
    "2020092018525770": "B208",
    "2022082709581351": "B216",
}

# 给定摄像头ip后三位，返回摄像头对应的Rid


def ip2room(ip):
    return ip_room_dict[ip]


# 给定房间门牌号id，返回对应的Rid
def door2room(door):
    return door_room_dict[door]


def get_conflict_appoints(appoint: Appoint, times: int = 1,
                          interval: int = 1, week_offset: int = 0,
                          exclude_this: bool = False,
                          no_cross_day=False, lock=False) -> QuerySet[Appoint]:
    '''

    获取以时间排序的冲突预约，可以加锁，但不负责开启事务，不应抛出异常

    :param appoint: 需要检测的第一个预约
    :type appoint: Appoint
    :param times: 检测次数, defaults to 1
    :type times: int, optional
    :param interval: 每次间隔的周数, defaults to 1
    :type interval: int, optional
    :param week_offset: 第一次检测时间距离提供预约的周数, defaults to 0
    :type week_offset: int, optional
    :param exclude_this: 排除检测的预约, defaults to False
    :type exclude_this: bool, optional
    :param no_cross_day: 是否假设预约都不跨天，可以简化查询, defaults to False
    :type no_cross_day: bool, optional
    :param lock: 查询时上锁, defaults to False
    :type lock: bool, optional
    :return: 时间升序排序的冲突预约集
    :rtype: QuerySet[Appoint]
    '''
    # 获取该房间的所有有效预约
    activate_appoints = Appoint.objects.not_canceled().filter(Room=appoint.Room)
    if lock:
        activate_appoints = activate_appoints.select_for_update()

    # 空的Q对象进行与和或运算的结果都是另一个操作数
    conditions = Q()
    if no_cross_day:
        conditions &= Q(
            # 开始比当前的结束时间早，结束比当前的开始时间晚
            Astart__time__lt=appoint.Afinish.time(),
            Afinish__time__gt=appoint.Astart.time(),
        )
        date_range = [
            appoint.Astart.date() + timedelta(weeks=week + week_offset)
            for week in range(0, times * interval, interval)
        ]
        conditions &= Q(
            Astart__date__in=date_range,
            Afinish__date__in=date_range,
        )
    else:
        for week in range(0, times * interval, interval):
            conditions |= Q(
                # 开始比当前的结束时间早
                Astart__lt=appoint.Afinish + \
                timedelta(weeks=week + week_offset),
                # 结束比当前的开始时间晚
                Afinish__gt=appoint.Astart + \
                timedelta(weeks=week + week_offset),
            )
    # 检查时预约还不应创建，冲突预约可以包含自身
    if conditions == Q():
        conflict_appoints = activate_appoints.none()
    else:
        conflict_appoints = activate_appoints.filter(conditions)
    if exclude_this:
        conflict_appoints = conflict_appoints.exclude(pk=appoint.pk)
    return conflict_appoints.order_by('Astart', 'Afinish')


def to_feedback_url(request: HttpRequest) -> str:
    """
    检查预约记录是否可以申诉。
    如果可以，向session添加传递到反馈填写界面的信息。
    最终函数返回跳转到的url。

    :param request: http请求
    :type request: HttpRequest
    :return: 即将跳转到的url
    :rtype: str
    """
    # 首先检查预约记录是否存在
    try:
        Aid = request.POST['feedback']
        appoint: Appoint = Appoint.objects.get(Aid=Aid)
    except:
        raise AssertionError("预约记录不存在！")

    # 然后检查预约记录是否可申诉
    assert appoint.Astatus in (
        Appoint.Status.VIOLATED,
        Appoint.Status.JUDGED,
    ), "该预约记录不可申诉！"

    appoint_student = appoint.major_student.name
    appoint_room = str(appoint.Room)
    appoint_start = appoint.Astart.strftime('%Y年%m月%d日 %H:%M')
    appoint_finish = appoint.Afinish.strftime('%H:%M')
    appoint_reason = appoint.get_status()

    # 向session添加信息
    request.session['feedback_type'] = '地下室预约问题反馈'
    request.session['feedback_url'] = appoint.get_admin_url()
    request.session['feedback_content'] = '\n'.join((
        f'申请人：{appoint_student}',
        f'房间：{appoint_room}',
        f'预约时间：{appoint_start} - {appoint_finish}',
        f'违规原因：{appoint_reason}',
    ))

    # 最终返回填写feedback的url
    return '/feedback/?argue'
