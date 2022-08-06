from yp_library.models import (
    Reader,
    Book,
    LendRecord,
)

from typing import Union, List, Tuple, Optional
from datetime import datetime

from django.contrib.auth.models import User
from django.db.models import Q, QuerySet
from django.http import QueryDict

from app.utils import check_user_type
from datetime import datetime, timedelta
from app.notification_utils import notification_create, bulk_notification_create
from app.models import Notification, Organization, NaturalPerson
from app.wechat_send import publish_notifications, WechatMessageLevel, WechatApp

from Appointment.models import Participant

__all__ = [
    'bookreturn_notifcation', 'get_readers_by_user', 'seach_books',
    'get_query_dict', 'get_my_records', 'get_lendinfo_by_readers'
]


def bookreturn_notification():
    """
    对每一条未归还的借阅记录进行检查
    在应还书时间前1天、应还书时间、应还书时间逾期5天发送还书提醒，提醒链接到“我的借阅”界面
    在应还书时间逾期7天，将借阅信息改为“超时扣分”，扣除1信用分并发送提醒
    """
    cr_time = datetime.now
    one_day_before = LendRecord.objects.filter(returned=False,
                                               due_time=cr_time -
                                               timedelta(days=1))
    now_return = LendRecord.objects.filter(returned=False, due_time=cr_time)
    five_days_after = LendRecord.objects.filter(returned=False,
                                                due_time=cr_time +
                                                timedelta(days=5))
    one_week_after = LendRecord.objects.filter(returned=False,
                                               due_time=cr_time +
                                               timedelta(weeks=1))
    sender = Organization.filter(oname="元培书房")
    URL = f"/lendinfo/"
    typename = Notification.Type.NEEDREAD
    
    receivers = []
    for record in one_day_before:
        receivers.append(record.reader_id.student_id)
    content = "您好！您现有未归还的图书，将于一天内借阅到期，请按时归还至元培书房！"
    bulk_notification_create(
        receivers=receivers,
        sender=sender,
        typename=typename,
        title=Notification.Title.YPLIB_INFORM,
        content=content,
        URL=URL,
        publish_to_wechat=True,
        publish_kws={
            'app': WechatApp._MESSAGE,
            'level': WechatMessageLevel.IMPORTANT,
        },
    )
    
    receivers = []
    for record in now_return:
        receivers.append(record.reader_id.student_id)
    content = "您好！您现有未归还的图书，已经借阅到期，请及时归还至元培书房！"
    bulk_notification_create(
        receivers=receivers,
        sender=sender,
        typename=typename,
        title=Notification.Title.YPLIB_INFORM,
        content=content,
        URL=URL,
        publish_to_wechat=True,
        publish_kws={
            'app': WechatApp._MESSAGE,
            'level': WechatMessageLevel.IMPORTANT,
        },
    )
    
    receivers = []
    for record in five_days_after:
        receivers.append(record.reader_id.student_id)
    content = "您好！您现有未归还的图书，已经借阅到期五天，请尽快归还至元培书房！到期一周未归还将扣除您的信用分1分！"
    bulk_notification_create(
        receivers=receivers,
        sender=sender,
        typename=typename,
        title=Notification.Title.YPLIB_INFORM,
        content=content,
        URL=URL,
        publish_to_wechat=True,
        publish_kws={
            'app': WechatApp._MESSAGE,
            'level': WechatMessageLevel.IMPORTANT,
        },
    )
    
    receivers = []
    for record in one_week_after:
        receiver = record.reader_id.student_id
        receivers.append(receiver)
        violate_stu = Participant.objects.get(Sid=receiver)
        if violate_stu.credit > 0:
            violate_stu.credit -= 1
    content = "您好！您现有未归还的图书，已经借阅到期一周，请尽快归还至元培书房！由于借阅超时一周，您已被扣除信用分1分！"
    bulk_notification_create(
        receivers=receivers,
        sender=sender,
        typename=typename,
        title=Notification.Title.YPLIB_INFORM,
        content=content,
        URL=URL,
        publish_to_wechat=True,
        publish_kws={
            'app': WechatApp._MESSAGE,
            'level': WechatMessageLevel.IMPORTANT,
        },
    )


def get_readers_by_user(user: User) -> QuerySet:
    """
    根据学号寻找与user关联的reader，要求必须为个人账号且账号必须通过学号关联至少一个reader，否则抛出AssertionError

    :param user: HttpRequest的User
    :type user: User
    :raises AssertionError: 只允许个人账户登录
    :raises AssertionError: user的学号没有关联任何书房账号
    :return: 与user关联的所有reader
    :rtype: QuerySet
    """
    valid, user_type, _ = check_user_type(user)
    if user_type != "Person":  # 只允许个人账户登录
        raise AssertionError('请使用个人账户登录!')
    readers = Reader.objects.filter(
        student_id=user.username).values()  # 获取与当前user的学号对应的所有readers
    if len(readers) == 0:
        raise AssertionError('您的学号没有关联任何书房账号!')
    return readers


def search_books(query_dict: dict) -> QuerySet:
    """
    根据给定的属性查询书

    :param query_dict: key为id/identity_code/title/author/publisher/returned, value为相应的query
        id和returned是精确查询，剩下四个是string按contains查询
        特别地，还支持全关键词查询：键keywords的值为一个列表[word, [field1, field2, ...]]，表示在给定的（多个）field中检索word（即“或”的关系）
        field可以是title/author/publisher
    :type query_dict: dict
    :return: 查询结果，每个记录是Book表的一行
    :rtype: QuerySet
    """
    query = Q()
    if query_dict.get("id", "") != "":
        query &= Q(id=int(query_dict["id"]))
    if query_dict.get("identity_code", "") != "":
        query &= Q(identity_code__contains=query_dict["identity_code"])
    if query_dict.get("title", "") != "":
        query &= Q(title__contains=query_dict["title"])
    if query_dict.get("author", "") != "":
        query &= Q(author__contains=query_dict["author"])
    if query_dict.get("publisher", "") != "":
        query &= Q(publisher__contains=query_dict["publisher"])
    if query_dict.get("returned", "") != "":
        query &= Q(returned=query_dict["returned"])

    if query_dict.get("keywords", "") != "" and query_dict["keywords"][0] != "":
        kw_query = Q()
        for kw_type in query_dict["keywords"][1]:
            if kw_type == "kw_title":
                kw_query |= Q(title__contains=query_dict["keywords"][0])
            elif kw_type == "kw_author":
                kw_query |= Q(author__contains=query_dict["keywords"][0])
            elif kw_type == "kw_publisher":
                kw_query |= Q(publisher__contains=query_dict["keywords"][0])
        query &= kw_query

    search_results = Book.objects.filter(query).values()
    return search_results


def get_query_dict(post_dict: QueryDict) -> dict:
    """
    从HttpRequest的POST中提取出用作search_books参数的query_dict

    :param post_dict: request.POST
    :type post_dict: QueryDict
    :return: 一个词典，key为id/identity_code/title/author/publisher/returned, value为相应的query
    :rtype: dict
    """
    # 采用五种查询条件，即"identity_code", "title", "author", "publisher"和"returned"，可视情况修改
    # returned是精确搜索，剩下四个是包含即可（contains）
    # （暂不提供通过id查询，因为id应该没有实际含义，用到的可能性不大）
    # search_books函数要求输入为一个词典，其条目对应"id", "identity_code", "title", "author", "publisher"和"returned"的query
    # 这里没有id的query，故query为空串
    # 此外，还提供“全关键词检索”，具体见search_books
    query_dict = {
        k: post_dict[k]
        for k in ["identity_code", "title", "author", "publisher"]
    }
    query_dict["id"] = ""

    if len(post_dict.getlist("returned")) == 1:  # 如果对returned有要求
        query_dict["returned"] = True
    else:  # 对returned没有要求
        query_dict["returned"] = ""

    # 全关键词检索
    query_dict["keywords"] = [
        post_dict["keywords"], ["kw_title", "kw_author", "kw_publisher"]
    ]

    return query_dict


def get_my_records(reader_id: str, returned: Optional[bool] = None, 
    status: Optional[Union[list, int]] = None) -> List[dict]:
    """
    查询给定读者的借书记录

    :param reader_id: reader的id
    :type reader_id: str
    :param returned: 如非空，则限定是否已归还, defaults to None
    :type returned: bool, optional
    :param status: 如非空，则限定当前状态, defaults to None
    :type status: Union[list, int], optional
    :return: 查询结果，每个记录包括val_list中的属性以及记录类型(key为'type': 
        对于已归还记录，False表示逾期记录，True表示正常记录；对于未归还记录，
        'normal'表示一般记录，'overtime'表示逾期记录，'approaching'表示接近
        期限记录即距离应归还时期<=1天)
    :rtype: List[dict]
    """
    all_records_list = LendRecord.objects.filter(reader_id=reader_id)
    val_list = ['book_id__title', 'lend_time', 'due_time', 'return_time']

    if returned is not None:
        results = all_records_list.filter(returned=returned)
        if returned:
            val_list.append('status')   # 已归还记录，增加申诉状态呈现
    else:
        results = all_records_list

    if isinstance(status, list):
        results = results.filter(status__in=status)
    elif isinstance(status, int):
        results = results.filter(status=status)
    
    records = list(results.values(*val_list))
    # 标记记录类型
    if returned:
        for record in records:
            if  record['return_time'] > record['due_time']:
                record['type'] = 'overtime'          # 逾期记录
            else:
                record['type'] = 'normal'           # 正常记录
    else:
        now_time = datetime.now()
        for record in records:
            # 计算距离应归还时间的天数
            delta_days = (record['due_time'] - now_time).total_seconds() / float(60 * 60 * 24)
            if delta_days > 1:
                record['type'] = 'normal'       # 一般记录
            elif delta_days < 0:
                record['type'] = 'overtime'     # 逾期记录
            else:
                record['type'] = 'approaching'  # 接近期限记录

    return records


def get_lendinfo_by_readers(readers: QuerySet) -> Tuple[List[dict], List[dict]]:
    '''
    查询同一user关联的读者的借阅信息

    :param readers: 与user关联的所有读者
    :type readers: QuerySet
    :return: 两个list，分别表示未归还记录和已归还记录
    :rtype: List[dict], List[dict]
    '''
    unreturned_records_list = []
    returned_records_list = []

    reader_ids = list(readers.values('id'))
    for reader_id in reader_ids:
        unreturned_records_list.extend(get_my_records(reader_id['id'], returned=False))
        returned_records_list.extend(get_my_records(reader_id['id'], returned=True))
        
    unreturned_records_list.sort(key=lambda r: r['due_time'])                 # 进行中记录按照应归还时间排序
    returned_records_list.sort(key=lambda r: r['return_time'], reverse=True)  # 已完成记录按照归还时间逆序排列
    
    return unreturned_records_list, returned_records_list
