from yp_library.models import (
    Reader,
    Book,
    LendRecord,
)

from django.contrib.auth.models import User
from django.db.models import Q, QuerySet
from django.http import QueryDict

from app.utils import check_user_type


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
    query_dict = {k: post_dict[k]
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
