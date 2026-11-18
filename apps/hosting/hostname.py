"""Hostname validation for custom app domains."""

from __future__ import annotations

import re

from django.conf import settings

from .hosts import _RESERVED_SLUGS

_LABEL = re.compile(r'^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$')


def normalize_hostname(value: str | None) -> str:
    """Lowercase host without port."""
    raw = (value or '').strip().lower()
    if not raw:
        return ''
    return raw.split(':', 1)[0].rstrip('.')


def validate_custom_hostname(hostname: str) -> str | None:
    """
    Return an error message if hostname is invalid for registration, else None.
    """
    host = normalize_hostname(hostname)
    if not host:
        return 'Hostname is required.'
    if len(host) > 253:
        return 'Hostname is too long.'
    if '..' in host or host.startswith('.') or host.endswith('.'):
        return 'Hostname is not valid.'
    labels = host.split('.')
    if len(labels) < 2:
        return 'Use a fully qualified hostname (at least two labels).'
    for label in labels:
        if not _LABEL.match(label):
            return 'Hostname contains invalid characters.'
    first = labels[0]
    if first in _RESERVED_SLUGS:
        return 'This hostname is reserved.'
    app_domain = (getattr(settings, 'HOSTING_APP_DOMAIN', '') or '').strip().lower()
    if app_domain:
        suffix = '.' + app_domain
        if host == app_domain or host.endswith(suffix):
            return 'Register a hostname outside the default app hosting domain.'
    return None
