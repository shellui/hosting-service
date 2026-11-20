"""Startup checks for hosted-app cookie scope and framing."""

import re

from django.conf import settings
from django.core.checks import Error, register

from apps.hosting.domain_scope import configured_cookie_parent_hosts, shared_cookie_parent_hosts

_UNSAFE_FRAME = re.compile(r'[\x00-\x1f;]')


def frame_ancestors_sources() -> str:
    """CSP source list for hosted ``frame-ancestors``. Unsafe values become ``'none'``."""
    raw = str(getattr(settings, 'HOSTING_FRAME_ANCESTORS', "'none'") or '').strip()
    if not raw or _UNSAFE_FRAME.search(raw):
        return "'none'"
    return raw


def frame_ancestors_denies_all(sources: str | None = None) -> bool:
    value = (sources if sources is not None else frame_ancestors_sources()).strip().lower()
    return value in {"'none'", 'none'}


@register(tags='security')
def shared_cookie_parent_error(app_configs, **kwargs):
    """Fail when hosted apps and a listed identity or admin host share a cookie parent."""
    matches = shared_cookie_parent_hosts()
    if not matches:
        return []
    parent = matches[0][1]
    listed = ', '.join(host for host, _parent in matches)
    return [
        Error(
            f'HOSTING_APP_DOMAIN shares the cookie parent {parent} with {listed}.',
            hint=(
                'Put identity and admin on a different registrable domain from hosted apps. '
                'For example, serve apps on shellui.app and keep identity and admin on shellui.com. '
                'List those hosts in HOSTING_COOKIE_PARENT_HOSTS.'
            ),
            id='hosting.E001',
        )
    ]


@register(deploy=True, tags='security')
def cookie_parent_hosts_required_in_production(app_configs, **kwargs):
    """Production must name the identity and admin hosts the cookie check compares."""
    if settings.DEBUG:
        return []
    if configured_cookie_parent_hosts():
        return []
    return [
        Error(
            'HOSTING_COOKIE_PARENT_HOSTS is empty.',
            hint=(
                'Set HOSTING_COOKIE_PARENT_HOSTS to the identity and admin hostnames, '
                'comma-separated. The startup check compares their cookie parent with '
                'HOSTING_APP_DOMAIN.'
            ),
            id='hosting.E002',
        )
    ]


@register(tags='security')
def frame_ancestors_value_is_safe(app_configs, **kwargs):
    raw = str(getattr(settings, 'HOSTING_FRAME_ANCESTORS', '') or '').strip()
    if raw and not _UNSAFE_FRAME.search(raw):
        return []
    return [
        Error(
            'HOSTING_FRAME_ANCESTORS is empty or contains a character that cannot appear in a CSP source list.',
            hint="Use 'none', or a space-separated list of origins such as https://shellui.com.",
            id='hosting.E003',
        )
    ]
