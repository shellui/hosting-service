"""URL configuration for hosting-service.

Platform routes (admin, API, docs, apex landing) apply on the root / reserved
hosts only. App subdomains are handled by ``HostedAppServeMiddleware`` so every
path — including ``/admin`` — serves the hosted SPA (React Router refreshes).
"""

from django.contrib import admin
from django.urls import include, path, re_path
from django.views.decorators.clickjacking import xframe_options_exempt
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.hosting.serve import AppServeView

from . import views

urlpatterns = [
    path('', views.root, name='root'),
    path('admin/', admin.site.urls),
    path('hosting/v1/', include('apps.hosting.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path(
        'api/docs/',
        xframe_options_exempt(SpectacularSwaggerView.as_view(url_name='schema')),
        name='swagger-ui',
    ),
    path(
        'api/docs/redoc/',
        xframe_options_exempt(SpectacularRedocView.as_view(url_name='schema')),
        name='redoc',
    ),
    # Fallback for app hosts if middleware is disabled. Excludes platform prefixes
    # so apex hosts keep admin / API / static on the URLConf above.
    re_path(
        r'^(?!hosting(?:/|$)|api(?:/|$)|admin(?:/|$)|static(?:/|$)|media(?:/|$))(?P<path>.*)$',
        AppServeView.as_view(),
        name='hosting-app-serve',
    ),
]
