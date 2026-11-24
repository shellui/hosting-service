"""OpenTelemetry gauges for hosted apps, deployments, and access.

The SDK reads the database when it collects, which is what a Prometheus scrape
used to do. ``company_id`` is the only attribute. Registration happens from
``config.telemetry`` after setup, so importing this module does not start the SDK.
"""

from __future__ import annotations

import time
from datetime import timedelta

# One collect asks every gauge. Share one database read across those callbacks.
_CACHE_SECONDS = 1.0
_cached_at = 0.0
_cached: dict[int, dict[str, int]] | None = None

# Prometheus name, snapshot key, unit, description.
GAUGES: tuple[tuple[str, str, str, str], ...] = (
    ('shellui_hosting_apps_total', 'apps_total', '1', 'Hosted apps for a company.'),
    (
        'shellui_hosting_apps_expired',
        'apps_expired',
        '1',
        'Hosted apps past their expires_at for a company.',
    ),
    ('shellui_hosting_deployments_total', 'deployments_total', '1', 'Deployments for a company.'),
    (
        'shellui_hosting_active_deployments',
        'active_deployments',
        '1',
        'Active deployments for a company.',
    ),
    (
        'shellui_hosting_artifact_bytes',
        'artifact_bytes',
        'By',
        'Total uploaded artifact bytes for a company.',
    ),
    (
        'shellui_hosting_deployments_24h',
        'deployments_24h',
        '1',
        'Deployments created in the last 24 hours.',
    ),
    (
        'shellui_hosting_deployments_7d',
        'deployments_7d',
        '1',
        'Deployments created in the last 7 days.',
    ),
    (
        'shellui_hosting_deployments_30d',
        'deployments_30d',
        '1',
        'Deployments created in the last 30 days.',
    ),
    (
        'shellui_hosting_access_pending',
        'access_pending',
        '1',
        'Pending hosting access requests for a company.',
    ),
    (
        'shellui_hosting_access_approved',
        'access_approved',
        '1',
        'Approved hosting access rows for a company.',
    ),
    (
        'shellui_hosting_access_denied',
        'access_denied',
        '1',
        'Denied hosting access rows for a company.',
    ),
)


def clear_snapshot_cache() -> None:
    global _cached_at, _cached
    _cached_at = 0.0
    _cached = None


def _company_ids() -> list[int]:
    from .models import App, CompanyHostingAccess, Deployment

    ids: set[int] = set()
    ids.update(App.objects.values_list('company_id', flat=True))
    ids.update(CompanyHostingAccess.objects.values_list('company_id', flat=True))
    ids.update(Deployment.objects.values_list('app__company_id', flat=True))
    return sorted(ids)


def _snapshot(company_id: int) -> dict[str, int]:
    from django.db.models import Count, Sum
    from django.utils import timezone

    from .models import AccessStatus, App, CompanyHostingAccess, Deployment, DeploymentStatus

    apps = App.objects.filter(company_id=company_id)
    deployments = Deployment.objects.filter(app__company_id=company_id)
    access = CompanyHostingAccess.objects.filter(company_id=company_id)
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    deployment_counts = {
        row['status']: row['count'] for row in deployments.values('status').annotate(count=Count('id'))
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


def _snapshots() -> dict[int, dict[str, int]]:
    global _cached_at, _cached
    now = time.monotonic()
    if _cached is not None and now - _cached_at < _CACHE_SECONDS:
        return _cached
    data = {company_id: _snapshot(company_id) for company_id in _company_ids()}
    _cached = data
    _cached_at = now
    return data


def register_hosting_metrics(meter) -> None:
    from opentelemetry.metrics import Observation
    from shellui_django.telemetry import canonical_metric_name

    def _callback(key: str):
        def callback(_options):
            for company_id, snap in _snapshots().items():
                yield Observation(snap[key], {'company_id': str(company_id)})

        return callback

    for prom_name, key, unit, description in GAUGES:
        meter.create_observable_gauge(
            canonical_metric_name(prom_name),
            callbacks=[_callback(key)],
            unit=unit,
            description=description,
        )
