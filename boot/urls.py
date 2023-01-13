"""Project's URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
"""
from django.contrib import admin
from django.urls import path, include
# from django.conf import settings
# from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("yppf/", include("app.urls")),
    path("underground/", include("Appointment.urls")),
    path("yplibrary/", include("yp_library.urls")),
    path("", include("app.urls"))
]

# Seems that develop server will add this automatically
# urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
