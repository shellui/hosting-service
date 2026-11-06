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
        'apps/<str:app_ref>/deployments/<uuid:deployment_id>/artifact-upload-url',
        views.DeploymentArtifactUploadUrlView.as_view(),
        name='hosting-deployment-artifact-upload-url',
    ),
    path(
        'apps/<str:app_ref>/deployments/<uuid:deployment_id>/artifact-upload-complete',
        views.DeploymentArtifactUploadCompleteView.as_view(),
        name='hosting-deployment-artifact-upload-complete',
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
    path(
        'apps/<str:app_ref>/domains',
        views.AppCustomDomainListCreateView.as_view(),
        name='hosting-app-domains-list',
    ),
    path(
        'apps/<str:app_ref>/domains/<uuid:domain_id>',
        views.AppCustomDomainDetailView.as_view(),
        name='hosting-app-domain-detail',
    ),
    path(
        'apps/<str:app_ref>/domains/<uuid:domain_id>/refresh',
        views.AppCustomDomainRefreshView.as_view(),
        name='hosting-app-domain-refresh',
    ),
    path(
        'apps/<str:app_ref>/environment',
        views.AppEnvironmentListCreateView.as_view(),
        name='hosting-app-environment-list',
    ),
    path(
        'apps/<str:app_ref>/environment/<str:key>',
        views.AppEnvironmentKeyView.as_view(),
        name='hosting-app-environment-key',
    ),
    path(
        'apps/<str:app_ref>/logs/runtime',
        views.AppRuntimeLogsView.as_view(),
        name='hosting-app-runtime-logs',
    ),
    path(
        'apps/<str:app_ref>/logs/requests',
        views.AppRequestLogsView.as_view(),
        name='hosting-app-request-logs',
    ),
    path('deploy-tokens', views.DeployTokenListCreateView.as_view(), name='hosting-deploy-token-list'),
    path(
        'deploy-tokens/<uuid:token_id>/revoke',
        views.DeployTokenRevokeView.as_view(),
        name='hosting-deploy-token-revoke',
    ),
    path('stats', views.StatsView.as_view(), name='hosting-stats'),
    path('metrics', views.HostingMetricsView.as_view(), name='hosting-metrics'),
    path('metrics/all', views.HostingGlobalMetricsView.as_view(), name='hosting-metrics-all'),
]
