from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from boottest.global_messages import wrong, succeed, message_url, transfer_message_context
from yp_library.utils import get_readers_by_user, search_books, get_query_dict
from app.utils import get_sidebar_and_navbar, check_user_access


@login_required(redirect_field_name="origin")
@check_user_access(redirect_url="/logout/")
def welcome(request):
    bar_display = get_sidebar_and_navbar(request.user, "元培书房")
    frontend_dict = {
        "bar_display": bar_display,
    }
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


def lendInfo(request):
    bar_display = get_sidebar_and_navbar(request.user, "借阅信息")
    frontend_dict = {
        "bar_display": bar_display,
    }
    return render(request, "yp_library/lendinfo.html", frontend_dict)
