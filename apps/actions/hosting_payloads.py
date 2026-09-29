"""Payload builders for hosting domain events."""

from __future__ import annotations

from apps.hosting.models import App, Deployment


def app_event_payload(app: App) -> dict:
    return {
        'app_id': str(app.id),
        'name': app.name,
        'slug': app.slug,
        'display_name': app.display_name,
        'company_id': app.company_id,
    }


def deployment_event_payload(deployment: Deployment, *, status: str | None = None, error: str | None = None) -> dict:
    app = deployment.app
    payload = {
        **app_event_payload(app),
        'deployment_id': str(deployment.id),
        'app_version': deployment.app_version,
        'shellui_version': deployment.shellui_version,
        'status': status or deployment.status,
    }
    if error:
        payload['error'] = error
    return payload
