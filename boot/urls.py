"""Project's URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("yppf/", include("app.urls")),
    path("underground/", include("Appointment.urls")),
    path("yplibrary/", include("yp_library.urls")),
    path("", include("app.urls"))
]

# 生产环境下自动返回空列表，请通过docker或服务器设置手动serve静态文件和媒体文件
# Static的URL配置在安装staticfiles应用时被默认覆盖，可通过--nostatic禁用
# urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
