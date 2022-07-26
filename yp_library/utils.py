from yp_library.models import (
    Reader,
    Book,
    LendRecord,
)

from django.contrib.auth.models import User
from django.db.models import Q, QuerySet

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
    my_readers = Reader.objects.filter(
        student_id=user.username).values()  # 获取与当前user的学号对应的所有readers
    if len(my_readers) == 0:
        raise AssertionError('您的学号没有关联任何书房账号!')
    return my_readers


def search_books(query_list: list) -> QuerySet:
    """
    根据给定的属性查询书

    :param query_list: 包含6个字符串的数组，分别对应id/identity_code/title/author/publisher/returned,
        id和returned是精确查询，剩下四个是string按contains查询
    :type query_list: list
    :return: 查询结果，每个记录是Book表的一行
    :rtype: QuerySet
    """
    query = Q()
    assert len(query_list) == 6
    for i, q in enumerate(query_list):
        if q != "":
            if i == 0:
                query &= Q(id=int(q))
            elif i == 1:
                query &= Q(identity_code__contains=q)  # 包含即可
            elif i == 2:
                query &= Q(title__contains=q)  # 包含即可
            elif i == 3:
                query &= Q(author__contains=q)  # 包含即可
            elif i == 4:
                query &= Q(publisher__contains=q)  # 包含即可
            elif i == 5:
                query &= Q(returned=q)
    search_results = Book.objects.filter(query).values()
    return search_results
