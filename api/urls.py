"""
Contains urls routing for miniapp APIs.
Place each API module in a separate folder, with its own urls.py file.
Then register the module in the urlpatterns list.
*Do not* put api implementations in the root directory of /api/.

Example:

```
api/
    __init__.py
    your_module/
        __init__.py
        urls.py
        serializers.py
        views.py
        tests.py
        ...

api/urls.py
path("your_module/", include("api.your_module.urls")),
```
"""

from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from django.conf import settings

app_name = "api"

urlpatterns = [
    path("v2/auth/", include("api.auth.urls")),
    path("v2/user/", include("api.user.urls")),
    path("v2/notification/", include("api.notification.urls")),
    path("v2/feedback/", include("api.feedback.urls")),
    path("v2/appoint/", include("api.appoint.urls")),
    path("v2/activity/", include("api.activity.urls")),
    path("v2/library/", include("api.library.urls")),
    path("v2/YQpools/", include("api.YQpools.urls")),
    path("v2/org/", include("api.org.urls")),
    path("v2/generic/", include("api.generic.urls")),
]

if settings.DEBUG:
    # API documentation
    urlpatterns += [
        path("schema/", SpectacularAPIView.as_view(), name="schema"),
        path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"),
             name="swagger-ui"),
        path("docs/redoc/",
             SpectacularRedocView.as_view(url_name="api:schema"), name="redoc"),
    ]
