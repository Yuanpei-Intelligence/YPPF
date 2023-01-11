"""Project's URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
"""
from django.contrib import admin
from django.urls import path, re_path, include
from django.conf import settings
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("yppf/", include("app.urls")),
    path("underground/", include("Appointment.urls")),
    path("yplibrary/", include("yp_library.urls")),
    path("", include("app.urls")),
    re_path(r"media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
]
