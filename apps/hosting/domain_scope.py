"""Compare hosted-app and platform service registrable domains.

A cookie with ``Domain=example.com`` is sent to every host under that name.
Hosted apps and identity or admin must not share that parent. The comparison
uses the last two hostname labels (``shellui.app``, ``shellui.com``).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from django.conf import settings

# Single-value settings that point at another Shellui service or public host.
_SERVICE_URL_SETTINGS = (
    'IDENTITY_SERVICE_URL',
    'IDENTITY_JWKS_URL',
    'EMAIL_SERVICE_URL',
    'SHELLUI_WEBSITE_URL',
    'SHELLUI_DOCS_URL',
    'SHELLUI_PLAYGROUND_URL',
    'SHELLUI_GITHUB_URL',
    'SHELLUI_AI_URL',
)
_SERVICE_URL_LIST_SETTINGS = (
    'CSRF_TRUSTED_ORIGINS',
    'CORS_ALLOWED_ORIGINS',
)


def registrable_domain(host: str | None) -> str | None:
    """Return the parent registrable domain, or None for IPs and single labels."""
    value = (host or '').strip().lower().rstrip('.')
    if not value or value == 'localhost':
        return None
    if value.startswith('[') and value.endswith(']'):
        value = value[1:-1]
    try:
        ipaddress.ip_address(value)
        return None
    except ValueError:
        pass
    labels = [label for label in value.split('.') if label]
    if len(labels) < 2:
        return None
    return '.'.join(labels[-2:])


def host_from_url(value: str | None) -> str | None:
    raw = (value or '').strip()
    if not raw:
        return None
    if '://' not in raw:
        raw = 'https://' + raw
    host = urlsplit(raw).hostname
    if not host:
        return None
    return host.lower().rstrip('.')


def configured_service_urls() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name in _SERVICE_URL_SETTINGS:
        value = getattr(settings, name, None)
        if value:
            pairs.append((name, str(value)))
    for name in _SERVICE_URL_LIST_SETTINGS:
        for item in getattr(settings, name, None) or []:
            text = str(item).strip()
            if text:
                pairs.append((name, text))
    return pairs


def shared_parent_service_urls(
    hosting_domain: str | None = None,
) -> list[tuple[str, str, str]]:
    """Return ``(setting, url, parent)`` rows that share a parent with hosting."""
    parent = registrable_domain(hosting_domain if hosting_domain is not None else settings.HOSTING_APP_DOMAIN)
    if not parent:
        return []
    matches: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name, url in configured_service_urls():
        other = registrable_domain(host_from_url(url))
        if other != parent:
            continue
        key = (name, url)
        if key in seen:
            continue
        seen.add(key)
        matches.append((name, url, parent))
    return matches
