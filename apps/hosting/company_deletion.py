"""Artifact cleanup for a deleted company (called by ``actions.purge_deleted_companies``)."""

from __future__ import annotations

from apps.hosting.models import App
from apps.hosting.serve import invalidate_serve_cache
from apps.hosting.services import delete_app_artifacts


def delete_company_artifacts(company_id: int) -> int:
    """Delete each app's artifacts and extracted files (S3 or disk), then the app."""
    deleted = 0
    for app in App._base_manager.filter(company_id=company_id):
        delete_app_artifacts(app)
        invalidate_serve_cache(app.slug)
        app.delete()
        deleted += 1
    return deleted
