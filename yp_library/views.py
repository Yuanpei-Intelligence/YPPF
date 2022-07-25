from django.shortcuts import render
from app.utils import get_sidebar_and_navbar

def welcome(request):
    bar_display=get_sidebar_and_navbar(request.user,"元培书房")
    frontend_dict = {
        "bar_display":bar_display,
    }  # 该字典存储提供给前端的信息
    return render(request, "yp_library/welcome.html", frontend_dict)


def search(request):
    bar_display=get_sidebar_and_navbar(request.user,"书籍搜索结果")
    frontend_dict = {
        "bar_display":bar_display,
     }  # 该字典存储提供给前端的信息
    return render(request, "yp_library/search.html", frontend_dict)


def lendInfo(request):
    bar_display=get_sidebar_and_navbar(request.user,"借阅信息")
    frontend_dict = {
        "bar_display":bar_display,
     }  # 该字典存储提供给前端的信息
    return render(request, "yp_library/lendinfo.html", frontend_dict)
