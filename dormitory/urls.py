from django.urls import path, include
from rest_framework.routers import DefaultRouter
from dormitory.views import DormitoryViewSet, DormitoryAssignmentViewSet

router = DefaultRouter()
router.register('dormitory', DormitoryViewSet, basename="dormitory")
router.register('dormitoryassignment', DormitoryAssignmentViewSet,
                basename="dormitoryassignment")

urlpatterns = [
    path('', include(router.urls)),
]
