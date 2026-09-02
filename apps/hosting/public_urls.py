"""Build public browsable URLs for hosted apps."""

from __future__ import annotations

from django.conf import settings


def _app_domain() -> str:
    return (getattr(settings, 'HOSTING_APP_DOMAIN', '') or '').strip().lstrip('.')


def _app_scheme() -> str:
    scheme = (getattr(settings, 'HOSTING_APP_SCHEME', '') or 'https').strip().lower()
    return scheme if scheme in {'http', 'https'} else 'https'


def build_app_url(slug: str) -> str:
    """Build a public URL for a hosted app: {scheme}://{site_slug}.{HOSTING_APP_DOMAIN}/"""
    slug = (slug or '').strip()
    if not slug:
        raise ValueError('slug is required')

    domain = _app_domain()
    if not domain:
        raise ValueError('HOSTING_APP_DOMAIN is required')

    return f'{_app_scheme()}://{slug}.{domain}/'
