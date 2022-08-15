from app.views_dependency import *
from app.models import (
    AcademicTagEntry,
    AcademicTextEntry,
)
from app.academic_utils import (
    get_search_results,
)
from app.utils import get_sidebar_and_navbar

__all__ = [
    'searchAcademic',
]


@login_required(redirect_field_name="origin")
@utils.check_user_access(redirect_url="/logout/")
@log.except_captured(EXCEPT_REDIRECT, source='academic_views[searchAcademic]', record_user=True)
def searchAcademic(request: HttpRequest) -> HttpResponse:
    """
    学术地图的搜索结果界面

    :param request: http请求
    :type request: HttpRequest
    :return: http响应
    :rtype: HttpResponse
    """
    frontend_dict = {}
    
    # POST表明搜索框发起检索
    if request.method == "POST" and request.POST:  
        query = request.POST["query"]  # 获取用户输入的关键词
        frontend_dict["academic_map_list"] = get_search_results(query)
        
    frontend_dict["bar_display"] = get_sidebar_and_navbar(request.user, "学术地图搜索结果")
    return render(request, "search_academic.html", frontend_dict)
