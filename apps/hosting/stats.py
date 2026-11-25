"""Aggregated hosting statistics."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from .models import App, CompanyHostingAccess, Deployment, DeploymentStatus


def build_hosting_stats(*, company_id: int | None = None) -> dict:
    apps = App.objects.all()
    deployments = Deployment.objects.all()
    access = CompanyHostingAccess.objects.all()

    if company_id is not None:
        apps = apps.filter(company_id=company_id)
        deployments = deployments.filter(app__company_id=company_id)
        access = access.filter(company_id=company_id)

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
        'company_id': company_id,
        'apps': apps.count(),
        'apps_expired': apps.filter(expires_at__isnull=False, expires_at__lt=now).count(),
        'deployments': deployments.count(),
        'deployments_by_status': deployment_counts,
        'active_deployments': deployment_counts.get(DeploymentStatus.ACTIVE, 0),
        'deployments_24h': deployments.filter(created_at__gte=day_ago).count(),
        'deployments_7d': deployments.filter(created_at__gte=week_ago).count(),
        'deployments_30d': deployments.filter(created_at__gte=month_ago).count(),
        'access': {
            'pending': access.filter(status='pending').count(),
            'approved': access.filter(status='approved').count(),
            'denied': access.filter(status='denied').count(),
        },
        'artifact_bytes': total_artifact_bytes,
    }
