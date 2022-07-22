from django.shortcuts import render


def welcome(request):
    return render(request, "yp_library/welcome.html", locals())


def search(request):
    return render(request, "yp_library/search.html", locals())


def lendInfo(request):
    return render(request, "yp_library/lendinfo.html", locals())
