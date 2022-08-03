from yp_library.models import (
    Reader,
    Book,
    LendRecord,
)

from typing import Union, List, Tuple, Optional
from datetime import datetime
import random

from django.contrib.auth.models import User
from django.db.models import Q, QuerySet
from django.http import QueryDict

from app.utils import check_user_type
from app.models import Activity
from app.constants import get_setting


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
    query_dict = {k: post_dict.get(k, "") # 这四个可有可无而keywords和returned必须有，这样可以兼容welcome页面的搜索
                  for k in ["identity_code", "title", "author", "publisher"]}
    query_dict["id"] = ""

    if len(post_dict.getlist("returned")) == 1:  # 如果对returned有要求
        query_dict["returned"] = True
    else:  # 对returned没有要求
        query_dict["returned"] = ""

    # 全关键词检索
    query_dict["keywords"] = [post_dict["keywords"],
                              ["kw_title", "kw_author", "kw_publisher"]]

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
                record['type'] = False          # 逾期记录
            else:
                record['type'] = True           # 正常记录
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
    
    return unreturned_records_list, returned_records_list


def get_library_activity(num: int) -> QuerySet:
    """
    获取书房欢迎页面展示的活动列表
    目前筛选活动的逻辑是：书房组织的、状态为报名中/等待中/进行中、活动开始时间越晚越优先

    :param num: 最多展示多少活动
    :type num: int
    :return: 展示的活动
    :rtype: list
    """
    all_valid_library_activities = Activity.objects.activated().filter(
        organization_id__oname=get_setting("library/organization_name"),
        status__in=[
            Activity.Status.APPLYING,
            Activity.Status.WAITING,
            Activity.Status.PROGRESSING
        ]
    ).order_by('-start')
    display_activities = all_valid_library_activities[:num].values()
    return display_activities


def get_recommended_or_newest_books(num: int, newest: bool = False) -> Union[QuerySet, list]:
    """
    获取推荐/新入馆书目（以id为入馆顺序）

    :param num: 最多展示多少本书
    :type num: int
    :param newest: 是否获取新入馆书目, defaults to False
    :type newest: bool, optional
    :return: 包含推荐书目的list/新入馆书目的QuerySet
    :rtype: Union[QuerySet, list]
    """
    # 获取随机记录的方法参考了
    # https://stackoverflow.com/questions/1731346/how-to-get-two-random-records-with-django/6405601#6405601
    book_counts = Book.objects.count()
    select_num = min(num, book_counts)
    all_books = Book.objects.all()
    if newest: # 最新到馆
        all_books_sorted = Book.objects.all().order_by('-id')
        return all_books_sorted[:select_num].values()
    else: # 随机推荐
        selected_ids = random.sample(range(0, book_counts), select_num)
        recommended_books = [all_books[id] for id in selected_ids]
        return recommended_books


def get_opening_time() -> Tuple[str, str]:
    """
    从setting读取开馆、闭馆时间（直接用字符串格式）

    :return: 开馆、闭馆时间
    :rtype: Tuple[str, str]
    """
    start_time = get_setting("library/open_time_start")
    end_time = get_setting("library/open_time_end")
    return start_time, end_time
