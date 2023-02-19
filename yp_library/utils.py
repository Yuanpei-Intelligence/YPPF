from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import QueryDict, HttpRequest

from app.utils import check_user_type
from app.notification_utils import bulk_notification_create
from app.config import UTYPE_PER
from app.models import Notification, Organization, Activity
from app.extern.wechat import WechatMessageLevel
from yp_library.models import (
    User,
    Reader,
    Book,
    LendRecord,
)
from yp_library.config import library_conf

__all__ = [
    'get_readers_by_user', 'search_books',
    'get_query_dict', 'get_my_records', 'get_lendinfo_by_readers'
]


def days_reminder(days: int, alert_msg: str):
    '''
    根据逾期时间时间向对应用户发送通知，不负责扣分

    :param days: 逾期时间
    :type days: int
    :param alert_msg: 通知内容
    :type alert_msg: str
    '''
    now = datetime.now()
    lendlist = LendRecord.objects.filter(
        returned=False,
        # 书房截止日期只包含日期信息，不包含时间
        due_time__date=now.date() - timedelta(days=days),
        lend_time__hour=now.hour,
    )

    receivers = lendlist.values_list('reader_id__student_id')
    receivers = User.objects.filter(username__in=receivers)
    _send_remind_notification(receivers, alert_msg)


def violate_reminder(days: int, alert_msg: str):
    '''
    扣除逾期超过指定天数的用户信用分一分并发送通知

    :param days: 逾期时间
    :type days: int
    :param alert_msg: 通知内容
    :type alert_msg: str
    '''
    before = datetime.now() - timedelta(hours=1)
    violate_lendlist = LendRecord.objects.filter(
        returned=False,
        due_time__lte=before - timedelta(days=days),
        lend_time__hour=before.hour,
        status=LendRecord.Status.NORMAL)

    # 逾期一周扣除信用分
    receivers = list(violate_lendlist.values_list(
        'reader_id__student_id', flat=True))
    receivers = User.objects.filter(username__in=receivers)
    # 绑定扣分和状态修改
    with transaction.atomic():
        for receiver in receivers:
            User.objects.modify_credit(receiver, -1, '书房：归还逾期')
        violate_lendlist.select_for_update().update(status=LendRecord.Status.OVERTIME)
    _send_remind_notification(receivers, alert_msg)


def _send_remind_notification(receivers: QuerySet[User], content: str):
    if not receivers:
        return
    # 发送通知
    URL = "/lendinfo/"
    typename = Notification.Type.NEEDREAD
    sender = Organization.objects.get(oname="何善衡图书室").get_user()
    bulk_notification_create(
        receivers=receivers,
        sender=sender,
        typename=typename,
        title=Notification.Title.YPLIB_INFORM,
        content=content,
        URL=URL,
        publish_to_wechat=True,
        publish_kws={
            'level': WechatMessageLevel.IMPORTANT,
        },
    )


def get_readers_by_user(user: User) -> QuerySet[Reader]:
    """
    根据学号寻找与user关联的reader，要求必须为个人账号且账号必须通过学号关联至少一个reader，否则抛出AssertionError

    :param user: HttpRequest的User
    :type user: User
    :raises AssertionError: 只允许个人账户登录
    :raises AssertionError: user的学号没有关联任何书房账号
    :return: 与user关联的所有reader
    :rtype: QuerySet[Reader]
    """
    valid, user_type, _ = check_user_type(user)
    if user_type != UTYPE_PER:  # 只允许个人账户登录
        raise AssertionError('您目前使用非个人账号登录，如要查询借阅记录，请使用个人账号。')
    # 获取与当前user的学号对应的所有readers
    readers = Reader.objects.filter(student_id=user.username)
    if len(readers) == 0:
        raise AssertionError('您的学号没有关联任何书房账号，如有借书需要，请前往书房开通账号。')
    return readers


def search_books(**query_dict) -> QuerySet[Book]:
    """
    根据给定的属性查询书

    :param query_dict: key为id/identity_code/title/author/publisher/returned, value为相应的query
        id和returned是精确查询，剩下四个是string按contains查询
        特别地，还支持全关键词查询：同时在identity_code/title/author/publisher中检索word
    :type query_dict: dict
    :return: 查询结果，每个记录是Book表的一行
    :rtype: QuerySet[Book]
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

    if query_dict.get("keywords", "") != "":
        kw_query = (Q(title__contains=query_dict["keywords"]) |
                    Q(author__contains=query_dict["keywords"]) |
                    Q(publisher__contains=query_dict["keywords"]) |
                    Q(identity_code__contains=query_dict["keywords"]))
        query &= kw_query

    search_results = Book.objects.filter(query).values()
    # TODO: Return type doesn't match
    return search_results


def get_query_dict(post_dict: QueryDict) -> Dict[str, Any]:
    """
    从HttpRequest的POST中提取出用作search_books参数的query_dict

    :param post_dict: request.POST
    :type post_dict: QueryDict
    :return: 一个词典，key为id/identity_code/title/author/publisher/returned/keywords, value为相应的query
    :rtype: dict
    """
    # 采用五种查询条件，即"identity_code", "title", "author", "publisher"和"returned"，可视情况修改
    # returned是精确搜索，剩下四个是包含即可（contains）
    # （暂不提供通过id查询，因为id应该没有实际含义，用到的可能性不大）
    # search_books函数要求输入为一个词典，其条目对应"id", "identity_code", "title", "author", "publisher"和"returned"的query
    # 这里没有id的query，故query为空串
    # 此外，还提供“全关键词检索”，具体见search_books
    query_dict = {}
    for query_type in ["identity_code", "title", "author", "publisher"]:
        if query_type in post_dict.keys():
            query_dict[query_type] = post_dict[query_type]

    # 上面的"identity_code", "title", "author", "publisher"在post_dict中可以没有（如welcome页面的搜索），
    # 下面的"returned"和"keywords"必须有
    if len(post_dict.getlist("returned")) == 1:  # 如果对returned有要求
        query_dict["returned"] = True

    # 全关键词检索
    query_dict["keywords"] = post_dict["keywords"]

    return query_dict


# TODO: Invalid type annotation
def get_my_records(reader_id: str, returned: Optional[bool] = None,
                   status: 'list | int | LendRecord.Status' = None) -> List[dict]:
    """
    查询给定读者的借书记录

    :param reader_id: reader的id
    :type reader_id: str
    :param returned: 如非空，则限定是否已归还, defaults to None
    :type returned: bool, optional
    :param status: 如非空，则限定当前状态, defaults to None
    :type status: Union[list, tuple, int, LendRecord.Status], optional
    :return: 查询结果，每个记录包括val_list中的属性以及记录类型(key为'type': 
        对于已归还记录，False表示逾期记录，True表示正常记录；对于未归还记录，
        'normal'表示一般记录，'overtime'表示逾期记录，'approaching'表示接近
        期限记录即距离应归还时期<=1天)
    :rtype: List[dict]
    """
    all_records_list = LendRecord.objects.filter(reader_id=reader_id)
    val_list = ['id', 'book_id__title', 'lend_time', 'due_time', 'return_time']

    if returned is not None:
        results = all_records_list.filter(returned=returned)
        if returned:
            val_list.append('status')   # 已归还记录，增加申诉状态呈现
    else:
        results = all_records_list

    if status is not None:
        if isinstance(status, (int, LendRecord.Status)):
            results = results.filter(status=status)
        else:
            results = results.filter(status__in=status)

    records = list(results.values(*val_list))
    # 标记记录类型
    if returned:
        for record in records:
            if record['return_time'] > record['due_time']:
                record['type'] = 'overtime_returned'     # 逾期记录
            else:
                record['type'] = 'returned'       # 正常记录
    else:
        now_time = datetime.now()
        for record in records:
            # 计算距离应归还时间的天数
            delta_days = (record['due_time'] -
                          now_time).total_seconds() / float(60 * 60 * 24)
            if delta_days > 1:
                record['type'] = 'normal'       # 一般记录
            elif delta_days < 0:
                record['type'] = 'overtime'     # 逾期记录
            else:
                record['type'] = 'approaching'  # 接近期限记录

    return records


# TODO: Invalid type annotation
def get_lendinfo_by_readers(readers: QuerySet[Reader]) -> Tuple[List[dict], List[dict]]:
    '''
    查询同一user关联的读者的借阅信息

    :param readers: 与user关联的所有读者
    :type readers: QuerySet[Reader]
    :return: 两个list，分别表示未归还记录和已归还记录
    :rtype: List[dict], List[dict]
    '''
    unreturned_records_list = []
    returned_records_list = []

    reader_ids = list(readers.values('id'))
    for reader_id in reader_ids:
        unreturned_records_list.extend(
            get_my_records(reader_id['id'], returned=False))
        returned_records_list.extend(
            get_my_records(reader_id['id'], returned=True))

    unreturned_records_list.sort(
        key=lambda r: r['due_time'])                 # 进行中记录按照应归还时间排序
    returned_records_list.sort(
        key=lambda r: r['return_time'], reverse=True)  # 已完成记录按照归还时间逆序排列

    return unreturned_records_list, returned_records_list


def get_library_activity(num: int) -> QuerySet[Activity]:
    """
    获取书房欢迎页面展示的活动列表
    目前筛选活动的逻辑是：书房组织的、状态为报名中/等待中/进行中、活动开始时间越晚越优先

    :param num: 最多展示多少活动
    :type num: int
    :return: 展示的活动
    :rtype: QuerySet[Activity]
    """
    all_valid_library_activities = Activity.objects.activated().filter(
        organization_id__oname=library_conf.organization_name,
        status__in=[
            Activity.Status.APPLYING,
            Activity.Status.WAITING,
            Activity.Status.PROGRESSING
        ]
    ).order_by('-start')
    display_activities = all_valid_library_activities[:num].values()
    # TODO: Return type doesn't match
    return display_activities


def get_recommended_or_newest_books(num: int, newest: bool = False) -> QuerySet[Book]:
    """
    获取推荐/新入馆书目（以id为入馆顺序）

    :param num: 最多展示多少本书
    :type num: int
    :param newest: 是否获取新入馆书目, defaults to False
    :type newest: bool, optional
    :return: 包含推荐书目/新入馆书目的QuerySet
    :rtype: QuerySet[Book]
    """
    book_counts = Book.objects.count()
    select_num = min(num, book_counts)
    if newest:  # 最新到馆
        all_books_sorted = Book.objects.all().order_by('-id')
        # TODO: Return type doesn't match
        return all_books_sorted[:select_num].values()
    else:  # 随机推荐
        recommended_books = Book.objects.order_by('?')[:num].values()
        # 这种获取随机记录的方法不适合于数据量极大的情况，见
        # https://stackoverflow.com/a/6405601
        # https://blog.csdn.net/CuGBabyBeaR/article/details/17141103
        # TODO: Return type doesn't match
        return recommended_books


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
        id = request.POST['feedback']
        record: LendRecord = LendRecord.objects.get(id=id)
    except:
        raise AssertionError("借阅记录不存在！")

    # 然后检查借阅记录是否可申诉
    # TODO: May encounter None Value
    assert record.due_time < record.return_time, "该借阅记录不可申诉！"

    # 将record的状态改为“申诉中”
    record.status = LendRecord.Status.APPEALING
    record.save()

    book_name = record.book_id.title
    lend_time = record.lend_time.strftime('%Y-%m-%d %H:%M')
    due_time = record.due_time.strftime('%Y-%m-%d %H:%M')
    return_time = record.return_time.strftime('%Y-%m-%d %H:%M')

    # 向session添加信息
    request.session['feedback_type'] = '书房借阅申诉'
    request.session['feedback_url'] = record.get_admin_url()
    request.session['feedback_content'] = '\n'.join((
        f'借阅书籍：{book_name}',
        f'借阅时间：{lend_time}',
        f'应归还时间：{due_time}',
        f'实际归还时间：{return_time}',
        '姓名：', '申诉理由：'
    ))

    # 最终返回填写feedback的url
    return '/feedback/?argue'
