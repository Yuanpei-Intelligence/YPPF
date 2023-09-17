from django.urls import include, path
from rest_framework.routers import DefaultRouter

from dormitory.views import (DormitoryAssignmentViewSet,
                             DormitoryAssignResultView, DormitoryRoutineQAView,
                             DormitoryViewSet)


router = DefaultRouter()
router.register('dormitory', DormitoryViewSet, basename='dormitory')
router.register('dormitoryassignment', DormitoryAssignmentViewSet,
                basename='dormitoryassignment')


urlpatterns = [
    path('', include(router.urls)),
    path('dormitory-routine-QA/', DormitoryRoutineQAView.as_view(),
         name='dormitory-routine-QA'),
    path('dormitory-assign-result/', DormitoryAssignResultView.as_view(),
         name='dormitory-assign-result'),
]
