"""Aggregated hosting statistics."""

from __future__ import annotations

from django.db.models import Count, Sum

from .models import App, CompanyHostingAccess, Deployment, DeploymentStatus


def build_hosting_stats(*, company_id: int | None = None) -> dict:
    apps = App.objects.all()
    deployments = Deployment.objects.all()
    access = CompanyHostingAccess.objects.all()

    if company_id is not None:
        apps = apps.filter(company_id=company_id)
        deployments = deployments.filter(app__company_id=company_id)
        access = access.filter(company_id=company_id)

    deployment_counts = {
        row['status']: row['count']
        for row in deployments.values('status').annotate(count=Count('id'))
    }
    total_artifact_bytes = deployments.aggregate(total=Sum('artifact_size'))['total'] or 0

    return {
        'company_id': company_id,
        'apps': apps.count(),
        'deployments': deployments.count(),
        'deployments_by_status': deployment_counts,
        'active_deployments': deployment_counts.get(DeploymentStatus.ACTIVE, 0),
        'access': {
            'pending': access.filter(status='pending').count(),
            'approved': access.filter(status='approved').count(),
            'denied': access.filter(status='denied').count(),
        },
        'artifact_bytes': total_artifact_bytes,
    }
