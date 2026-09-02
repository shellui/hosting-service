from django.urls import path

from . import views

urlpatterns = [
    path('health', views.HealthView.as_view(), name='hosting-health'),
    path('access', views.AccessView.as_view(), name='hosting-access'),
    path('access/request', views.AccessRequestView.as_view(), name='hosting-access-request'),
    path('preview', views.PreviewPrepareView.as_view(), name='hosting-preview-prepare'),
    path('apps', views.AppListCreateView.as_view(), name='hosting-app-list'),
    path('apps/<str:app_ref>', views.AppDetailView.as_view(), name='hosting-app-detail'),
    path(
        'apps/<str:app_ref>/renew-expiry',
        views.AppRenewExpiryView.as_view(),
        name='hosting-app-renew-expiry',
    ),
    path(
        'apps/<str:app_ref>/deployments',
        views.DeploymentListCreateView.as_view(),
        name='hosting-deployment-list',
    ),
    path(
        'apps/<str:app_ref>/deployments/<uuid:deployment_id>/upload',
        views.DeploymentUploadView.as_view(),
        name='hosting-deployment-upload',
    ),
    path(
        'apps/<str:app_ref>/deployments/<uuid:deployment_id>/finalize',
        views.DeploymentFinalizeView.as_view(),
        name='hosting-deployment-finalize',
    ),
    path(
        'apps/<str:app_ref>/deployments/<uuid:deployment_id>/rollback',
        views.DeploymentRollbackView.as_view(),
        name='hosting-deployment-rollback',
    ),
    path('stats', views.StatsView.as_view(), name='hosting-stats'),
]
