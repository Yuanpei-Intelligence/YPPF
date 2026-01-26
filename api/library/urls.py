"""
URL routes for library API.
"""
from rest_framework.routers import DefaultRouter

from api.library.views import LibraryViewSet

app_name = "library"

router = DefaultRouter()
router.register(r'', LibraryViewSet, basename='library')

urlpatterns = router.urls
