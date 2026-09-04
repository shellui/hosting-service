"""Sync hosted app origins to identity-service OAuth redirect allowlist."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests
from django.conf import settings

from .public_urls import build_app_url

logger = logging.getLogger(__name__)


def app_origin_for_sync(app) -> str:
    """Canonical origin for a hosted app (scheme://host[:port], no trailing slash)."""
    url = build_app_url(app.slug)
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f'Invalid app URL for slug {app.slug!r}: {url!r}')
    return f'{parts.scheme}://{parts.netloc}'


def _identity_base_url() -> str | None:
    base = (getattr(settings, 'IDENTITY_SERVICE_URL', None) or '').strip().rstrip('/')
    return base or None


def upsert_hosting_oauth_redirect(app, *, access_token: str | None) -> None:
    """
    Register the app origin on the company OAuth redirect allowlist using the
    caller's identity JWT. No-op when identity URL or token is missing.
    """
    base = _identity_base_url()
    token = (access_token or '').strip()
    if not base or not token:
        logger.debug('Skipping oauth redirect upsert: identity URL or user token missing')
        return
    try:
        origin = app_origin_for_sync(app)
    except ValueError as exc:
        logger.warning('Cannot sync oauth redirect for app %s: %s', app.slug, exc)
        return
    label = (app.display_name or app.slug or '')[:150]
    url = f'{base}/api/v1/hosting-oauth-redirects'
    try:
        response = requests.put(
            url,
            json={
                'base_url': origin,
                'label': label,
            },
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            timeout=float(getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10) or 10),
        )
        if response.status_code >= 400:
            logger.warning(
                'Identity oauth redirect upsert failed for %s (%s): %s %s',
                origin,
                app.slug,
                response.status_code,
                (response.text or '')[:300],
            )
        else:
            logger.info('Synced hosting oauth redirect %s for company %s', origin, app.company_id)
    except requests.RequestException as exc:
        logger.warning('Identity oauth redirect upsert error for %s: %s', app.slug, exc)


def delete_hosting_oauth_redirect_origin(
    *,
    origin: str,
    access_token: str | None,
) -> None:
    """Remove a hosting-managed allowlist row for the caller's company (JWT)."""
    base = _identity_base_url()
    token = (access_token or '').strip()
    if not base or not token:
        logger.debug('Skipping oauth redirect delete: identity URL or user token missing')
        return
    url = f'{base}/api/v1/hosting-oauth-redirects'
    try:
        response = requests.delete(
            url,
            json={'base_url': origin},
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            timeout=float(getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10) or 10),
        )
        if response.status_code >= 400:
            logger.warning(
                'Identity oauth redirect delete failed for %s: %s %s',
                origin,
                response.status_code,
                (response.text or '')[:300],
            )
        else:
            logger.info('Removed hosting oauth redirect %s', origin)
    except requests.RequestException as exc:
        logger.warning('Identity oauth redirect delete error for %s: %s', origin, exc)
