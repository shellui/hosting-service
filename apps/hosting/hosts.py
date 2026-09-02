"""Resolve hosted app slugs from request hostnames."""

from __future__ import annotations

import ipaddress

# Hostnames that should never map to a hosted app (API / dev landing).
_RESERVED_HOSTS = frozenset({'localhost', 'testserver'})

# First labels reserved for infrastructure subdomains.
_RESERVED_SLUGS = frozenset({'www', 'hosting', 'api', 'admin'})


def slug_from_host(host: str) -> str | None:
    """
    Extract a site slug from any multi-label hostname.

    Examples:
        vpzzsxvzsmp7.shellui.local -> vpzzsxvzsmp7
        vpzzsxvzsmp7.shellui.app   -> vpzzsxvzsmp7
        vpzzsxvzsmp7.example.com   -> vpzzsxvzsmp7
    """
    host = (host or '').split(':', 1)[0].strip().lower().rstrip('.')
    if not host or host in _RESERVED_HOSTS:
        return None

    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass

    labels = host.split('.')
    if len(labels) < 3:
        return None

    slug = labels[0].strip()
    if not slug or slug in _RESERVED_SLUGS:
        return None

    return slug
