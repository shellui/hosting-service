"""Single source of truth for hosting-service environment variables.

Pure Python: no Django settings, database, Redis or env needed. Used by
``manage.py generate_env``, to render ``.env.example``, and by the tests that
keep both in sync with ``config/settings.py`` and ``docs/configuration.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

PLACEHOLDER = 'change-me'


@dataclass(frozen=True)
class Var:
    name: str
    default: str = ''
    group: str = ''


@dataclass(frozen=True)
class Required:
    """Required in production (DEBUG=false)."""

    name: str
    comment: str


REQUIRED = (
    Required('SECRET_KEY', 'Signs sessions and CSRF tokens. At least 50 characters. Generated.'),
    Required('DEBUG', 'Production mode.'),
    Required('ALLOWED_HOSTS', 'Public host names, comma-separated, no scheme.'),
    Required('CSRF_TRUSTED_ORIGINS', 'Full HTTPS origin of this service.'),
    Required('HOSTING_APP_DOMAIN', 'Domain for hosted apps, for example shellui.app.'),
    Required('IDENTITY_SERVICE_URL', 'identity-service origin (OAuth redirect sync).'),
    Required('IDENTITY_ISSUER', 'JWT iss claim, the identity-service URL.'),
    Required('IDENTITY_AUDIENCE', 'JWT aud claim.'),
    Required('IDENTITY_JWKS', 'Pinned JWKS JSON from {IDENTITY_SERVICE_URL}/.well-known/jwks.json.'),
    Required('REDIS_URL', 'Shared cache and job broker.'),
    Required('POSTGRES_DATABASE_URL', 'PostgreSQL DSN. Leave empty to use SQLite.'),
)

OPTIONAL = (
    Var('LOG_LEVEL', 'INFO', 'Runtime'),
    Var('SETUP_TOKEN', ''),
    Var('DJANGO_ADMIN_ENABLED', 'true'),
    Var('HOSTING_SERVICE_PORT', '8002'),
    Var('SQLITE_PATH', 'db.sqlite3', 'Database: SQLite unless POSTGRES_DATABASE_URL is set'),
    Var('POSTGRES_SSL_REQUIRE', 'true'),
    Var('IDENTITY_JWKS_FILE', '', 'Identity and JWT'),
    Var('IDENTITY_JWKS_URL', ''),
    Var('IDENTITY_SYNC_TIMEOUT', '10'),
    Var('JWKS_CACHE_TTL', '900'),
    Var('JWKS_TIMEOUT', '15'),
    Var('JWKS_RETRIES', '2'),
    Var('JWT_ALGORITHMS', 'RS256'),
    Var('JWT_HS256_FALLBACK_SECRET', ''),
    Var('ALLOW_JWT_HS256_FALLBACK', 'false'),
    Var('HOSTING_APP_SCHEME', 'https', 'Public URLs and serving'),
    Var('HOSTING_ALLOW_ANY_HOST', 'false'),
    Var('HOSTING_DEBUG_OPEN', 'false'),
    Var('HOSTING_SERVE_CACHE_TTL_SECONDS', '45'),
    Var('HOSTING_PREVIEW_TTL_DAYS', '7'),
    Var('HOSTING_MAX_APPS_PER_COMPANY', '5', 'Quotas'),
    Var('HOSTING_MAX_DEPLOYMENTS_PER_APP', '20'),
    Var('HOSTING_MAX_UPLOAD_BYTES', '100M'),
    Var('HOSTING_MAX_EXTRACT_FILES', '5000'),
    Var('HOSTING_MAX_EXTRACT_BYTES', '500M'),
    Var('HOSTING_MAX_EXTRACT_FILE_BYTES', '100M'),
    Var('DATA_UPLOAD_MAX_MEMORY_SIZE', '12M'),
    Var('HOSTING_BACKEND', 'filesystem', 'Artifact storage: filesystem or s3'),
    Var('MEDIA_ROOT', ''),
    Var('HOSTING_KEY_PREFIX', 'hosting'),
    Var('AWS_ACCESS_KEY_ID', ''),
    Var('AWS_SECRET_ACCESS_KEY', ''),
    Var('AWS_STORAGE_BUCKET_NAME', ''),
    Var('AWS_S3_REGION_NAME', 'us-east-1'),
    Var('AWS_S3_ENDPOINT_URL', ''),
    Var('AWS_S3_CUSTOM_DOMAIN', ''),
    Var('AWS_S3_SIGNATURE_VERSION', 's3v4'),
    Var('AWS_S3_ADDRESSING_STYLE', ''),
    Var('HOSTING_RATE_LIMIT_ENABLED', 'true', 'Rate limits (requests per window)'),
    Var('HOSTING_RATE_LIMIT_DEPLOY', '30'),
    Var('HOSTING_RATE_LIMIT_UPLOAD', '20'),
    Var('HOSTING_RATE_LIMIT_DESTRUCTIVE', '10'),
    Var('HOSTING_RATE_LIMIT_ACCESS_REQUEST', '10'),
    Var('CORS_ALLOW_ALL_ORIGINS', 'true', 'CORS and HTTPS'),
    Var('CORS_ALLOW_CREDENTIALS', 'false'),
    Var('CORS_ALLOWED_ORIGINS', ''),
    Var('CORS_ALLOW_PRIVATE_NETWORK', 'true'),
    Var('TRUSTED_PROXY_IPS', ''),
    Var('SECURE_SSL_REDIRECT', 'true'),
    Var('SECURE_HSTS_SECONDS', '31536000'),
    Var('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'true'),
    Var('SECURE_HSTS_PRELOAD', 'false'),
    Var('SESSION_COOKIE_SECURE', 'true'),
    Var('CSRF_COOKIE_SECURE', 'true'),
    Var('SCHEDULER_ENABLED', 'true', 'Scheduled jobs'),
    Var('CELERY_BROKER_URL', ''),
    Var('CELERY_WORKER_CONCURRENCY', '2'),
    Var('CELERY_BEAT_SCHEDULE_FILE', '/tmp/celerybeat-schedule'),
    Var('ACTIONS_OUTBOX_MAX_ATTEMPTS', '8', 'Shellui Actions (webhooks)'),
    Var('ACTIONS_WEBHOOK_TIMEOUT_SECONDS', '5'),
    Var('ACTIONS_WEBHOOK_RETRY_LEASE_SECONDS', '120'),
    Var('ACTIONS_WEBHOOK_DISPATCH_WORKERS', '4'),
    Var('ACTIONS_WEBHOOK_SYNC_DELIVERY', 'false'),
    Var('ACTIONS_WEBHOOK_ALLOW_PRIVATE', 'false'),
    Var('EVENT_LOG_RETENTION_DAYS', '7'),
    Var('EMAIL_SERVICE_API_KEY', '', 'Email notifications: off while EMAIL_SERVICE_API_KEY is empty'),
    Var('EMAIL_SERVICE_URL', 'https://email.shellui.com'),
    Var('EMAIL_SERVICE_ALLOW_PRIVATE', 'false'),
    Var('ROOT_REDIRECT_URL', '', 'Apex landing'),
    Var('SHELLUI_WEBSITE_URL', 'https://shellui.com'),
    Var('SHELLUI_DOCS_URL', 'https://docs.shellui.com'),
    Var('SHELLUI_PLAYGROUND_URL', 'https://playground.shellui.com'),
    Var('SHELLUI_GITHUB_URL', 'https://github.com/shellui'),
    Var('SHELLUI_AI_URL', 'https://shellui.ai'),
    Var('HOSTING_REGION', ''),
    Var('SENTRY_DSN', '', 'Error reporting'),
    Var('SENTRY_ENVIRONMENT', 'production'),
    Var('SENTRY_RELEASE', ''),
    Var('SENTRY_TRACES_SAMPLE_RATE', '0'),
    Var('GUNICORN_WORKERS', '2', 'Gunicorn (Docker entrypoint)'),
    Var('GUNICORN_THREADS', '2'),
    Var('GUNICORN_TIMEOUT', '120'),
)


def all_names() -> set[str]:
    return {v.name for v in REQUIRED} | {v.name for v in OPTIONAL}


def optional_lines(skip: frozenset[str] = frozenset()) -> list[str]:
    """Commented-out optional vars with their default, grouped by topic."""
    lines: list[str] = []
    for var in OPTIONAL:
        if var.name in skip:
            continue
        if var.group:
            lines.extend(['', f'# {var.group}'])
        lines.append(f'# {var.name}={var.default}')
    return lines


_EXAMPLE_HEADER = """\
# hosting-service settings. Full reference: docs/configuration.md
# Generated from config/env_registry.py: python manage.py generate_env --example > .env.example
# Production: python manage.py generate_env --host hosting.example.com
# Copy to .env for local runs. Commented-out lines show the default the code uses.

# Required
# Local development key only. Production needs 50+ random characters (generate_env).
SECRET_KEY=django-insecure-local-development-only-0123456789abcdef
# Local development only. Unset means false (production).
DEBUG=true
# Local identity-service. JWKS is fetched from {url}/.well-known/jwks.json in DEBUG.
IDENTITY_SERVICE_URL=http://localhost:8000
# Local dev: skip the company waitlist (refused when DEBUG=false).
HOSTING_DEBUG_OPEN=true

# Required when DEBUG=false (production)
ALLOWED_HOSTS=
CSRF_TRUSTED_ORIGINS=
HOSTING_APP_DOMAIN=
IDENTITY_ISSUER=
IDENTITY_AUDIENCE=
IDENTITY_JWKS=
REDIS_URL=
POSTGRES_DATABASE_URL=

# Optional (defaults shown)"""


def render_example() -> str:
    """The content of ``.env.example`` (local development)."""
    return '\n'.join([_EXAMPLE_HEADER, *optional_lines(skip=frozenset({'HOSTING_DEBUG_OPEN'}))]) + '\n'
