from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from boottest.global_messages import wrong, succeed, message_url, transfer_message_context
from yp_library.utils import (
    get_readers_by_user,
    search_books,
    get_query_dict,
    get_lendinfo_by_readers,
    get_library_activity, 
    get_recommended_or_newest_books, 
    get_opening_time,
)
from app.utils import get_sidebar_and_navbar, check_user_access

DISPLAY_ACTIVITY_NUM = 3 # 首页展示的书房活动数量
DISPLAY_RECOMMENDATION_NUM = 5 # 首页展示的推荐书目数量
# DISPLAY_NEW_BOOK_NUM = 5 # 首页展示的新入馆书目数量


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
def welcome(request: HttpRequest) -> HttpResponse:
    """
    书房首页，提供近期活动、随机推荐、开馆时间；
    首页的查询功能应该可以通过前端转到search页面，这里未做处理

    :param request: 进入书房首页的请求
    :type request: HttpRequest
    :return: 书房首页
    :rtype: HttpResponse
    """
    bar_display = get_sidebar_and_navbar(request.user, "元培书房")
    frontend_dict = {
        "bar_display": bar_display,
    }
    transfer_message_context(request.GET, frontend_dict,
                             normalize=True)
    
    # 检查用户身份
    # 要求必须为个人账号且账号必须通过学号关联至少一个reader，否则抛出AssertionError
    # 如果首页对账号没有要求，可以删掉这部分
    try:
        readers = get_readers_by_user(request.user)
    except AssertionError as e:
        frontend_dict["warn_message"] = "提示：馆藏查询、查看借阅记录等功能需要开通书房账号!"
        
    # 获取首页展示的近期活动
    frontend_dict["activities"] = get_library_activity(num=DISPLAY_ACTIVITY_NUM)
    # 获取开馆时间
    frontend_dict["opening_time_start"], frontend_dict["opening_time_end"] = get_opening_time()
    # 获取随机推荐书目
    frontend_dict["recommendation"] = get_recommended_or_newest_books(
        num=DISPLAY_RECOMMENDATION_NUM, newest=False)
    # 获取最新到馆书目（按id从大到小），暂不启用
    # frontend_dict["newest_books"] = get_recommended_or_newest_books(
    #     num=DISPLAY_NEW_BOOK_NUM, newest=True)

    return render(request, "yp_library/welcome.html", frontend_dict)


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
def search(request: HttpRequest) -> HttpResponse:
    """
    图书检索页面

    :param request: 进入检索页面/发起检索的请求
    :type request: HttpRequest
    :return: 仍为search页面，显示检索结果
    :rtype: HttpResponse
    """
    bar_display = get_sidebar_and_navbar(request.user, "书籍搜索结果")
    frontend_dict = {
        "bar_display": bar_display,
    }
    transfer_message_context(request.GET, frontend_dict,
                             normalize=True)

    # 检查用户身份
    # 要求必须为个人账号且账号必须通过学号关联至少一个reader，否则抛出AssertionError
    # 如果图书检索对账号没有要求，可以删掉这部分
    try:
        readers = get_readers_by_user(request.user)
    except AssertionError as e:
        return redirect(message_url(wrong(e)))

    if request.method == "POST" and request.POST:  # POST表明发起检索
        query_dict = get_query_dict(request.POST)  # 提取出检索条件
        frontend_dict["search_results_list"] = search_books(query_dict)

    return render(request, "yp_library/search.html", frontend_dict)


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
def lendInfo(request: HttpRequest) -> HttpResponse:
    '''
    借阅信息页面

    :param request: 进入借阅信息页面的请求
    :type request: HttpRequest
    :return: lendinfo页面，显示与当前user学号关联的所有读者的所有借阅记录
    :rtype: HttpResponse
    '''
    bar_display = get_sidebar_and_navbar(request.user, "借阅信息")
    frontend_dict = {
        "bar_display": bar_display,
    }
    transfer_message_context(request.GET, frontend_dict,
                             normalize=True)

    # 检查用户身份
    # 要求必须为个人账号且账号必须通过学号关联至少一个reader，否则抛出AssertionError
    try:
        readers = get_readers_by_user(request.user)
    except AssertionError as e:
        return redirect(message_url(wrong(e)))

    unreturned_records_list, returned_records_list = get_lendinfo_by_readers(readers)
    frontend_dict['unreturned_records_list'] = unreturned_records_list
    frontend_dict['returned_records_list'] = returned_records_list

    return render(request, "yp_library/lendinfo.html", frontend_dict)
