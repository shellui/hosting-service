"""Sync hosted app origins to identity-service OAuth redirect allowlist."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests
from django.conf import settings

from .public_urls import build_app_url

logger = logging.getLogger(__name__)

_JWKS_SUFFIX = '/.well-known/jwks.json'
# Default from settings when no identity host is configured. Not a sync target.
_PLACEHOLDER_ORIGINS = frozenset(
    {
        'http://localhost:8000',
        'http://127.0.0.1:8000',
    }
)
_SYNC_ATTEMPTS = 3


class RedirectSyncResult:
    """Outcome of one identity allowlist upsert. Falsy when the origin was not registered."""

    def __init__(self, *, registered: bool, origin: str = '', warning: str = ''):
        self.registered = registered
        self.origin = origin
        self.warning = warning

    def __bool__(self) -> bool:
        return self.registered

    def as_api(self) -> dict:
        payload = {
            'oauth_redirect_registered': self.registered,
            'oauth_redirect_origin': self.origin,
        }
        if self.warning:
            payload['oauth_redirect_warning'] = self.warning
        return payload


def app_origin_for_sync(app) -> str:
    """Canonical origin for a hosted app (scheme://host[:port], no trailing slash)."""
    url = build_app_url(app.slug)
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f'Invalid app URL for slug {app.slug!r}: {url!r}')
    return f'{parts.scheme}://{parts.netloc}'


def _identity_base_url() -> str | None:
    """Identity origin for redirect sync.

    ``IDENTITY_SERVICE_URL`` wins. Otherwise use an explicit
    ``IDENTITY_JWKS_URL`` of the form ``{origin}/.well-known/jwks.json``
    when the JWKS document is pinned. Production often sets only that URL.
    """
    base = (getattr(settings, 'IDENTITY_SERVICE_URL', None) or '').strip().rstrip('/')
    if base:
        return base
    # A fetch URL is not enough: tests and local runs set IDENTITY_JWKS_URL
    # without running redirect sync.
    if getattr(settings, 'IDENTITY_JWKS_SOURCE', None) not in {'env', 'file'}:
        return None
    jwks = (getattr(settings, 'IDENTITY_JWKS_URL', None) or '').strip().rstrip('/')
    if not jwks.endswith(_JWKS_SUFFIX):
        return None
    origin = jwks[: -len(_JWKS_SUFFIX)].rstrip('/')
    if not origin or origin in _PLACEHOLDER_ORIGINS:
        return None
    return origin


def _identity_error_detail(response) -> str:
    detail = ''
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = str(body.get('error') or body.get('detail') or '').strip()
    if not detail:
        detail = (response.text or '').strip().replace('\n', ' ')[:200]
    reason = f'Identity rejected the origin (HTTP {response.status_code})'
    if detail:
        reason = f'{reason}: {detail}'
    else:
        reason = f'{reason}.'
    if response.status_code == 403 and detail == 'Forbidden':
        reason = f'{reason}. Only a company owner or staff user can register hosted origins.'
    return reason


def _sync_request(method, url: str, *, payload: dict, headers: dict, timeout: float):
    """PUT/DELETE with retries on network errors and HTTP 5xx."""
    response = None
    for attempt in range(1, _SYNC_ATTEMPTS + 1):
        try:
            response = method(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException:
            if attempt == _SYNC_ATTEMPTS:
                raise
            continue
        if response.status_code < 500 or attempt == _SYNC_ATTEMPTS:
            return response
    return response


def upsert_hosting_oauth_redirect(app, *, access_token: str | None) -> RedirectSyncResult:
    """
    Register the app origin on the company OAuth redirect allowlist using the
    caller's identity JWT. Identity accepts this call from staff or a company owner.
    """
    base = _identity_base_url()
    token = (access_token or '').strip()
    try:
        origin = app_origin_for_sync(app)
    except ValueError as exc:
        logger.warning('Cannot sync oauth redirect for app %s: %s', getattr(app, 'slug', '?'), exc)
        return RedirectSyncResult(registered=False, warning=str(exc))
    if not base or not token:
        if token and not base:
            warning = 'Identity service URL is not configured.'
        elif base and not token:
            warning = 'Caller access token was not available to forward.'
        else:
            warning = 'Identity service URL is not configured and the caller access token was missing.'
        logger.warning('Skipping oauth redirect upsert for %s: %s', origin, warning)
        return RedirectSyncResult(registered=False, origin=origin, warning=warning)
    label = (app.display_name or app.slug or '')[:150]
    url = f'{base}/api/v1/hosting-oauth-redirects'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    timeout = float(getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10) or 10)
    try:
        response = _sync_request(
            requests.put,
            url,
            payload={'base_url': origin, 'label': label},
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        warning = f'Could not reach identity: {exc}'
        logger.warning('Identity oauth redirect upsert error for %s: %s', app.slug, warning)
        return RedirectSyncResult(registered=False, origin=origin, warning=warning)
    if response.status_code >= 400:
        warning = _identity_error_detail(response)
        logger.warning(
            'Identity oauth redirect upsert failed for %s (%s): %s',
            origin,
            app.slug,
            warning,
        )
        return RedirectSyncResult(registered=False, origin=origin, warning=warning)
    logger.info('Synced hosting oauth redirect %s for company %s', origin, app.company_id)
    return RedirectSyncResult(registered=True, origin=origin)


def delete_hosting_oauth_redirect_origin(
    *,
    origin: str,
    access_token: str | None,
) -> bool:
    """Remove a hosting-managed allowlist row for the caller's company (JWT)."""
    base = _identity_base_url()
    token = (access_token or '').strip()
    if not base or not token:
        logger.debug('Skipping oauth redirect delete: identity URL or user token missing')
        return False
    url = f'{base}/api/v1/hosting-oauth-redirects'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    timeout = float(getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10) or 10)
    try:
        response = _sync_request(
            requests.delete,
            url,
            payload={'base_url': origin},
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning('Identity oauth redirect delete error for %s: %s', origin, exc)
        return False
    if response.status_code >= 400:
        logger.warning(
            'Identity oauth redirect delete failed for %s: %s %s',
            origin,
            response.status_code,
            (response.text or '')[:300],
        )
        return False
    logger.info('Removed hosting oauth redirect %s', origin)
    return True
