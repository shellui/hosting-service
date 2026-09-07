"""Prometheus-style metrics for hosting-service.

Exposition is JWT-protected (see HostingMetricsView / HostingGlobalMetricsView).
Company-scoped `/metrics` uses a fresh registry so other tenants never appear
in the text dump.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from .models import AccessStatus, App, CompanyHostingAccess, Deployment, DeploymentStatus

_LABELS = ('company_id',)


def _company_ids() -> list[int]:
    ids: set[int] = set()
    ids.update(App.objects.values_list('company_id', flat=True))
    ids.update(CompanyHostingAccess.objects.values_list('company_id', flat=True))
    ids.update(Deployment.objects.values_list('app__company_id', flat=True))
    return sorted(ids)


def _snapshot(company_id: int) -> dict[str, int]:
    apps = App.objects.filter(company_id=company_id)
    deployments = Deployment.objects.filter(app__company_id=company_id)
    access = CompanyHostingAccess.objects.filter(company_id=company_id)
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    deployment_counts = {
        row['status']: row['count']
        for row in deployments.values('status').annotate(count=Count('id'))
    }
    total_artifact_bytes = deployments.aggregate(total=Sum('artifact_size'))['total'] or 0

    return {
        'apps_total': apps.count(),
        'apps_expired': apps.filter(expires_at__isnull=False, expires_at__lt=now).count(),
        'deployments_total': deployments.count(),
        'active_deployments': deployment_counts.get(DeploymentStatus.ACTIVE, 0),
        'artifact_bytes': total_artifact_bytes,
        'deployments_24h': deployments.filter(created_at__gte=day_ago).count(),
        'deployments_7d': deployments.filter(created_at__gte=week_ago).count(),
        'deployments_30d': deployments.filter(created_at__gte=month_ago).count(),
        'access_pending': access.filter(status=AccessStatus.PENDING).count(),
        'access_approved': access.filter(status=AccessStatus.APPROVED).count(),
        'access_denied': access.filter(status=AccessStatus.DENIED).count(),
    }


def _bind_gauges(registry: CollectorRegistry) -> dict[str, Gauge]:
    return {
        'apps_total': Gauge(
            'shellui_hosting_apps_total',
            'Hosted apps for a company.',
            _LABELS,
            registry=registry,
        ),
        'apps_expired': Gauge(
            'shellui_hosting_apps_expired',
            'Hosted apps past their expires_at for a company.',
            _LABELS,
            registry=registry,
        ),
        'deployments_total': Gauge(
            'shellui_hosting_deployments_total',
            'Deployments for a company.',
            _LABELS,
            registry=registry,
        ),
        'active_deployments': Gauge(
            'shellui_hosting_active_deployments',
            'Active deployments for a company.',
            _LABELS,
            registry=registry,
        ),
        'artifact_bytes': Gauge(
            'shellui_hosting_artifact_bytes',
            'Total uploaded artifact bytes for a company.',
            _LABELS,
            registry=registry,
        ),
        'deployments_24h': Gauge(
            'shellui_hosting_deployments_24h',
            'Deployments created in the last 24 hours.',
            _LABELS,
            registry=registry,
        ),
        'deployments_7d': Gauge(
            'shellui_hosting_deployments_7d',
            'Deployments created in the last 7 days.',
            _LABELS,
            registry=registry,
        ),
        'deployments_30d': Gauge(
            'shellui_hosting_deployments_30d',
            'Deployments created in the last 30 days.',
            _LABELS,
            registry=registry,
        ),
        'access_pending': Gauge(
            'shellui_hosting_access_pending',
            'Pending hosting access requests for a company.',
            _LABELS,
            registry=registry,
        ),
        'access_approved': Gauge(
            'shellui_hosting_access_approved',
            'Approved hosting access rows for a company.',
            _LABELS,
            registry=registry,
        ),
        'access_denied': Gauge(
            'shellui_hosting_access_denied',
            'Denied hosting access rows for a company.',
            _LABELS,
            registry=registry,
        ),
    }


def _set_company(gauges: dict[str, Gauge], company_id: int) -> None:
    cid = str(company_id)
    snap = _snapshot(company_id)
    for name, gauge in gauges.items():
        gauge.labels(company_id=cid).set(snap[name])


def metrics_http_body(company_id: int | None = None) -> bytes:
    """Serialize Prometheus text. When ``company_id`` is set, only that tenant is included."""
    registry = CollectorRegistry()
    gauges = _bind_gauges(registry)
    if company_id is None:
        for cid in _company_ids():
            _set_company(gauges, cid)
    else:
        _set_company(gauges, company_id)
    return generate_latest(registry)


METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST
