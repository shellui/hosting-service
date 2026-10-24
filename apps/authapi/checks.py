"""Django system checks for authapi."""

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.core.exceptions import ImproperlyConfigured

from config.settings import _env_int

# Django's own security.W009 uses the same length and insecure prefix, as a
# deploy warning. Production must fail the check instead.
SECRET_KEY_MIN_LENGTH = 50
SECRET_KEY_PLACEHOLDER_PREFIXES = ('django-insecure-',)
SECRET_KEY_PLACEHOLDERS = frozenset(
    {
        'django-insecure-12345678901234567890123456789012',
        'change-me-generate-a-strong-secret-key',
    }
)


def secret_key_problem(secret_key: str | None) -> str | None:
    """Return an error sentence when a production key must be refused."""
    key = (secret_key or '').strip()
    if not key:
        return 'SECRET_KEY is empty.'
    if key in SECRET_KEY_PLACEHOLDERS or key.startswith(SECRET_KEY_PLACEHOLDER_PREFIXES):
        return (
            'SECRET_KEY is a known placeholder. Generate a new key before '
            'DEBUG=false.'
        )
    if len(key) < SECRET_KEY_MIN_LENGTH:
        return f'SECRET_KEY is shorter than {SECRET_KEY_MIN_LENGTH} characters.'
    return None


@register(deploy=True, tags='security')
def secret_key_refused_outside_debug(app_configs, **kwargs):
    """
    Error when DEBUG is false and SECRET_KEY is empty, a placeholder, or short.

    A deploy check, so `check --deploy` (run by the Docker entrypoint) fails.
    `manage.py test` sets DEBUG false and must still run with the CI key.
    """
    if settings.DEBUG:
        return []
    try:
        secret_key = settings.SECRET_KEY
    except ImproperlyConfigured:
        secret_key = ''
    problem = secret_key_problem(secret_key)
    if not problem:
        return []
    return [
        Error(
            problem,
            hint=(
                'Generate a key with: python -c "from django.core.management.utils '
                'import get_random_secret_key; print(get_random_secret_key())"'
            ),
            id='authapi.E005',
        )
    ]


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
