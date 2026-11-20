"""Compare hosted-app and identity or admin cookie parents.

A cookie with ``Domain=example.com`` is sent to every host under that name.
Hosted apps and identity or admin must not share that parent. The comparison
uses the last two hostname labels (``shellui.app``, ``shellui.com``).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from django.conf import settings


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


def configured_cookie_parent_hosts() -> list[str]:
    """Hosts from ``HOSTING_COOKIE_PARENT_HOSTS`` (identity and admin)."""
    raw = getattr(settings, 'HOSTING_COOKIE_PARENT_HOSTS', None) or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(',') if item.strip()]
    hosts: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        hosts.append(text)
    return hosts


def shared_cookie_parent_hosts(
    hosting_domain: str | None = None,
) -> list[tuple[str, str]]:
    """Return ``(host, parent)`` rows that share a cookie parent with hosting."""
    parent = registrable_domain(hosting_domain if hosting_domain is not None else settings.HOSTING_APP_DOMAIN)
    if not parent:
        return []
    matches: list[tuple[str, str]] = []
    seen: set[str] = set()
    for host in configured_cookie_parent_hosts():
        other = registrable_domain(host_from_url(host))
        if other != parent or host in seen:
            continue
        seen.add(host)
        matches.append((host, parent))
    return matches
