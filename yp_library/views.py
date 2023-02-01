from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from utils.views import SecureTemplateView
from utils.global_messages import wrong, succeed, message_url, transfer_message_context
from yp_library.utils import (
    get_readers_by_user,
    search_books,
    get_query_dict,
    get_lendinfo_by_readers,
    get_library_activity, 
    get_recommended_or_newest_books, 
    get_opening_time,
    to_feedback_url,
)
from app.utils import get_sidebar_and_navbar, check_user_access

DISPLAY_ACTIVITY_NUM = 3 # 首页展示的书房活动数量
DISPLAY_RECOMMENDATION_NUM = 5 # 首页展示的推荐书目数量
# DISPLAY_NEW_BOOK_NUM = 5 # 首页展示的新入馆书目数量


class WelcomeView(SecureTemplateView):
    """
    书房首页，提供近期活动、随机推荐、开馆时间；
    首页的查询功能应该可以通过前端转到search页面，这里未做处理
    """

    login_required = True
    template_name = "yp_library/welcome.html"

    def check_get(self, request: HttpRequest) -> HttpResponse | None:
        return super().check_get(request)

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse | None:
        bar_display = get_sidebar_and_navbar(request.user, "元培书房")
        # 借阅记录
        try:
            readers = get_readers_by_user(request.user)
        except AssertionError as e:
            records_list = []
        else:
            unreturned_records_list, returned_records_list = get_lendinfo_by_readers(readers)
            records_list = unreturned_records_list + returned_records_list
        # 开放时间
        opening_time_start, opening_time_end = get_opening_time()

        transfer_message_context(request.GET, self.extra_context,
                                normalize=True)
        self.extra_context.update({
            "activities": get_library_activity(num=DISPLAY_ACTIVITY_NUM),
            "bar_display": bar_display,
            "opening_time_start": opening_time_start,
            "opening_time_end": opening_time_end,
            "records_list": records_list,
            "recommendation": get_recommended_or_newest_books(
                        num=DISPLAY_RECOMMENDATION_NUM, newest=False),
        })
        return


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

    # 检索页面不再额外检查是否个人账号、是否关联reader

    if request.method == "POST" and request.POST:  # POST表明发起检索
        query_dict = get_query_dict(request.POST)  # 提取出检索条件
        frontend_dict["search_results_list"] = search_books(**query_dict)

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
    # 要求用户为个人账号且账号必须通过学号关联至少一个reader，否则给出提示语
    try:
        readers = get_readers_by_user(request.user)
    except AssertionError as e:
        wrong(str(e), frontend_dict)
        frontend_dict['unreturned_records_list'] = []
        frontend_dict['returned_records_list'] = []
        return render(request, "yp_library/lendinfo.html", frontend_dict)

    unreturned_records_list, returned_records_list = get_lendinfo_by_readers(readers)
    frontend_dict['unreturned_records_list'] = unreturned_records_list
    frontend_dict['returned_records_list'] = returned_records_list
    
    # 用户发起申诉
    if request.method == 'POST' and request.POST:
        if request.POST.get('feedback') is not None:
            try:
                url = to_feedback_url(request)
                return redirect(url)
            except AssertionError as e:
                wrong(str(e), frontend_dict) 

    return render(request, "yp_library/lendinfo.html", frontend_dict)
