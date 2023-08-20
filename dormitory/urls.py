from django.urls import include, path
from rest_framework.routers import DefaultRouter

from dormitory.views import (DormitoryAssignmentViewSet,
                             DormitoryAssignResultView, DormitoryRoutineQAView,
                             DormitoryViewSet)

app_name = 'dormitory'

router = DefaultRouter()
router.register('dormitory', DormitoryViewSet, basename="dormitory")
router.register('dormitoryassignment', DormitoryAssignmentViewSet,
                basename="dormitoryassignment")


urlpatterns = [
    path('', include(router.urls)),
    path("dormitoryRoutineQA/", DormitoryRoutineQAView.as_view(),
         name="dormitoryRoutineQA"),
    path("dormitoryAssignResult/", DormitoryAssignResultView.as_view(),
         name="dormitoryAssignResult"),
]
