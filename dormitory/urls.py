from django.urls import path, include
from rest_framework.routers import DefaultRouter

from dormitory.views import (
    DormitoryViewSet, DormitoryAssignmentViewSet, DormitoryRoutineQAView, DormitoryAssignResultView
)


router = DefaultRouter()
router.register('dormitory', DormitoryViewSet, basename="dormitory")
router.register('dormitoryassignment', DormitoryAssignmentViewSet,
                basename="dormitoryassignment")


urlpatterns = [
    path('', include(router.urls)),
    # ('temporary_dormitory/', TemporaryDormitoryView.as_view()),
    path("dormitoryRoutineQA/", DormitoryRoutineQAView.as_view(), name="dormitoryRoutineQA"),
    path("dormitoryAssignResult/", DormitoryAssignResultView.as_view(), name="dormitoryAssignResult"),
]
