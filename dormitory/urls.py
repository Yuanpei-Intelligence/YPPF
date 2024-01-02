from django.urls import include, path
from rest_framework.routers import DefaultRouter

from dormitory.views import (DormitoryAssignmentViewSet,
                             DormitoryAssignResultView, DormitoryRoutineQAView,
                             DormitoryViewSet, AgreementJsonView,
                             AgreementView, DormitoryAgreementViewSet)


router = DefaultRouter()
router.register('dormitory', DormitoryViewSet, basename='dormitory')
router.register('dormitoryassignment', DormitoryAssignmentViewSet,
                basename='dormitoryassignment')
router.register('agreement-query2', DormitoryAgreementViewSet,
                basename='agreement-query2')


urlpatterns = [
    path('', include(router.urls)),
    path('routine-QA/', DormitoryRoutineQAView.as_view(),
         name='dormitory-routine-QA'),
    path('assign-result/', DormitoryAssignResultView.as_view(),
         name='dormitory-assign-result'),
    path('agreement/', AgreementView.as_view(),
         name='agreement'),
    path('agreement-query/', AgreementJsonView.as_view(),
         name='agreement-query'),
]
