"""
URL routes for activity API.
"""
from rest_framework.routers import DefaultRouter

from api.activity.views import ActivityViewSet

app_name = "activity"

router = DefaultRouter()
router.register(r'', ActivityViewSet, basename='activity')

urlpatterns = router.urls
