from django.shortcuts import render


def welcome(request):
    frontend_dict = {}  # 该字典存储提供给前端的信息
    return render(request, "yp_library/welcome.html", frontend_dict)


def search(request):
    frontend_dict = {}  # 该字典存储提供给前端的信息
    return render(request, "yp_library/search.html", frontend_dict)


def lendInfo(request):
    frontend_dict = {}  # 该字典存储提供给前端的信息
    return render(request, "yp_library/lendinfo.html", frontend_dict)
