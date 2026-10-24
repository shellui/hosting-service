"""Resolve hosted app slugs from request hostnames."""

from __future__ import annotations

import ipaddress

from django.conf import settings

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

    ``HOSTING_APP_DOMAIN`` itself (and ``www.`` on it) is the platform apex,
    never an app, so a region domain such as ``eu.shellui.app`` works.
    """
    host = _normalize(host)
    if not host or host in _RESERVED_HOSTS:
        return None

    app_domain = _normalize(getattr(settings, 'HOSTING_APP_DOMAIN', ''))
    if app_domain and host in (app_domain, f'www.{app_domain}'):
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


def _normalize(host: str) -> str:
    return (host or '').split(':', 1)[0].strip().lower().rstrip('.').lstrip('.')
