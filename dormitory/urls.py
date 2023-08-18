from django.urls import path, include
from rest_framework.routers import DefaultRouter

from dormitory.views import (
    DormitoryViewSet, DormitoryAssignmentViewSet, TemporaryDormitoryView
)


router = DefaultRouter()
router.register('dormitory', DormitoryViewSet, basename="dormitory")
router.register('dormitoryassignment', DormitoryAssignmentViewSet,
                basename="dormitoryassignment")


urlpatterns = [
    path('', include(router.urls)),
    path('temporary_dormitory/', TemporaryDormitoryView.as_view())
]
