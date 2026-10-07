"""Django system checks for authapi."""

from django.conf import settings
from django.core.checks import Error, Warning, register

from config.settings import _env_int


@register(deploy=True, tags='security')
def shared_cache_recommended_for_multi_worker(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    backend = settings.CACHES.get('default', {}).get('BACKEND', '')
    if 'locmem' not in backend.lower():
        return []
    workers = _env_int('GUNICORN_WORKERS', 2)
    if workers <= 1:
        return []
    return [
        Warning(
            'LocMemCache is not shared across Gunicorn workers — hosting rate limits '
            'are per-worker.',
            hint=(
                'Add a Redis service and set REDIS_URL (e.g. redis://redis:6379/0) on the '
                'hosting-service container. LocMem is fine for single-worker or local dev.'
            ),
            id='authapi.W001',
        )
    ]


REDIS_URL_REQUIRED_MESSAGE = 'REDIS_URL is required when DEBUG is false (example: redis://redis:6379/0).'


@register(deploy=True, tags='caches')
def redis_required_in_production(app_configs, **kwargs):
    """
    Production needs Redis: the shared cache (hosting rate limits) and the scheduled
    jobs broker. LocMem is per process, so rate limits break across Gunicorn workers.

    A deploy check, so `check --deploy` (run by the Docker entrypoint) fails, while
    tests and other management commands still run. The entrypoint also exits early
    with the same message before migrations. See tools/docker-entrypoint.sh.
    """
    if settings.DEBUG:
        return []
    if (getattr(settings, 'REDIS_URL', '') or '').strip():
        return []
    return [
        Error(
            REDIS_URL_REQUIRED_MESSAGE,
            hint=(
                'Add a Redis service and set REDIS_URL on every hosting-service container '
                '(web and worker), also with SCHEDULER_ENABLED=false: Redis backs the shared '
                'cache (rate limits) and the scheduled jobs. Use DEBUG=true only for local '
                'development without Redis.'
            ),
            id='authapi.E004',
        )
    ]
