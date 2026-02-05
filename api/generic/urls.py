"""
URL routes for generic API (e.g. homepage carousel).
"""
from django.urls import path

from api.generic.views import CarouselView

app_name = "generic"

urlpatterns = [
    path("carousel/", CarouselView.as_view(), name="carousel"),
]
