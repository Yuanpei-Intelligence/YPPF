"""
URL routes for YQpools API.
"""
from rest_framework.routers import DefaultRouter

from api.YQpools.views import PoolsViewSet

app_name = "YQpools"

router = DefaultRouter()
router.register(r'', PoolsViewSet, basename='pools')

urlpatterns = router.urls
