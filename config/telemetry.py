"""OpenTelemetry setup for hosting-service.

Export stays off until ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or a signal-specific
endpoint) is set. ``OTEL_SDK_DISABLED=true`` forces it off. Gunicorn, the
Celery worker, and ``manage.py`` each call :func:`setup_service_telemetry`.
A second call in the same process, including after a fork, does not build
another provider.
"""

from __future__ import annotations

import logging
import os
import sys
import tomllib
from pathlib import Path

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

SERVICE_NAME = 'hosting-service'

_REGISTERED_PROVIDER: int | None = None


def _package_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / 'pyproject.toml'
    with pyproject.open('rb') as handle:
        version = str(tomllib.load(handle).get('project', {}).get('version', '')).strip()
    return version


def _text_setting(name: str) -> str:
    """Env value, then the Django setting once settings have loaded."""
    raw = os.getenv(name, '').strip()
    if raw:
        return raw
    try:
        from django.conf import settings

        return str(getattr(settings, name, '') or '').strip()
    except Exception:
        logger.debug('shellui telemetry: %s is not available yet', name, exc_info=True)
        return ''


def _note_deploy_env() -> None:
    """The SDK reads these. Recording the names keeps them in the env registry."""
    endpoint = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', '')
    headers = os.getenv('OTEL_EXPORTER_OTLP_HEADERS', '')
    service_name = os.getenv('OTEL_SERVICE_NAME', '')
    resource_attributes = os.getenv('OTEL_RESOURCE_ATTRIBUTES', '')
    logger.debug(
        'otel env present endpoint=%s headers=%s service_name=%s resource_attributes=%s',
        bool(endpoint.strip()),
        bool(headers.strip()),
        bool(service_name.strip()),
        bool(resource_attributes.strip()),
    )


def setup_service_telemetry(*, span_exporter=None, metric_reader=None) -> bool:
    """Enable traces, metrics, and log correlation. Return True when active."""
    _note_deploy_env()
    from shellui_django.telemetry import setup_telemetry

    version = _package_version()
    enabled = setup_telemetry(
        SERVICE_NAME,
        service_version=version or None,
        environment=_text_setting('SENTRY_ENVIRONMENT') or None,
        region=_text_setting('HOSTING_REGION') or None,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
    if not enabled:
        return False
    if _in_celery_worker():
        return True
    _ensure_apps_ready()
    if register_metrics() and span_exporter is None and metric_reader is None:
        logger.info('OpenTelemetry export is on for %s', SERVICE_NAME)
    return True


def _in_celery_worker() -> bool:
    # The Celery thread pool shares one Django DB connection across threads, so the
    # metric reader thread must not query there. Gunicorn publishes the gauges.
    return bool(sys.argv) and os.path.basename(sys.argv[0]) == 'celery'


def _ensure_apps_ready() -> None:
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def register_metrics() -> bool:
    """Create observable instruments on the active meter. Return True the first time."""
    global _REGISTERED_PROVIDER
    from shellui_django.telemetry import get_meter
    from shellui_django.telemetry._state import state

    if not state.active or state.meter_provider is None:
        return False
    provider_id = id(state.meter_provider)
    if _REGISTERED_PROVIDER == provider_id:
        return False
    meter = get_meter('shellui.hosting')
    from apps.actions.scheduled_job_metrics import register_scheduled_job_metrics
    from apps.hosting.metrics import register_hosting_metrics

    register_hosting_metrics(meter)
    register_scheduled_job_metrics(meter)
    _REGISTERED_PROVIDER = provider_id
    return True


def reset_metric_registration() -> None:
    """Allow tests to register instruments on a new meter provider."""
    global _REGISTERED_PROVIDER
    _REGISTERED_PROVIDER = None


class ShelluiSpanMiddleware(MiddlewareMixin):
    """Attach opaque Shellui ids to the current server span.

    Runs after the view, while the server span is still recording. Emails and
    other free text are not set. ``set_shellui_attributes`` drops them anyway.
    """

    def process_response(self, request, response):
        _annotate_span(request)
        return response


def _annotate_span(request) -> None:
    from django.conf import settings
    from shellui_django.telemetry import set_shellui_attributes

    user = getattr(request, 'user', None)
    company_id = None
    user_id = None
    extra: dict[str, str] = {}
    if getattr(user, 'is_authenticated', False):
        company_id = getattr(user, 'company_id', None)
        agent_id = getattr(user, 'agent_id', None)
        if agent_id:
            extra['agent_id'] = str(agent_id)
        else:
            raw_user = getattr(user, 'user_id', None)
            if isinstance(raw_user, int) and not isinstance(raw_user, bool) and raw_user > 0:
                user_id = raw_user
        deploy_token_id = getattr(user, 'deploy_token_id', None)
        if deploy_token_id:
            extra['deploy_token_id'] = str(deploy_token_id)
    region = str(getattr(settings, 'HOSTING_REGION', '') or '').strip()
    # Span attributes accept a single opaque token. A display phrase stays on the page only.
    if region and ' ' not in region:
        extra['region'] = region
    if company_id is None and user_id is None and not extra:
        return
    set_shellui_attributes(company_id=company_id, user_id=user_id, attributes=extra or None)
