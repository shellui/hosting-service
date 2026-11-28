"""Startup checks for hosted-app cookie scope and framing."""

import re

from django.conf import settings
from django.core.checks import Error, register

from apps.hosting.domain_scope import configured_cookie_parent_hosts, shared_cookie_parent_hosts

_HOST_LABEL = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
_ORIGIN = re.compile(r'^https://(?P<host>[^/:?#@\s]+)(?::(?P<port>[0-9]{1,5}))?$')


class FrameAncestorsError(ValueError):
    """``HOSTING_FRAME_ANCESTORS`` is not a strict list of allowed framing sources."""


def parse_frame_ancestors(raw: str) -> list[str]:
    """Validate a ``frame-ancestors`` source list one source at a time.

    Allowed, separated by spaces only:

    - ``'self'``
    - ``'none'``, and only on its own
    - an exact ``https`` origin: ``https://host`` or ``https://host:port``, no path

    Everything else is refused: ``*``, bare schemes such as ``https:``, wildcard hosts such
    as ``https://*.shellui.app``, commas, ``http`` origins, paths, unquoted keywords, and
    ``'none'`` next to other sources.
    """
    text = str(raw or '').strip()
    if not text:
        raise FrameAncestorsError('the list is empty')
    if not text.isascii() or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        raise FrameAncestorsError('it contains a control or non-ASCII character')
    if ',' in text or ';' in text:
        raise FrameAncestorsError('separate sources with spaces, not commas or semicolons')
    sources: list[str] = []
    for token in text.split():
        if token == "'self'":
            value = token
        elif token == "'none'":
            value = token
        else:
            match = _ORIGIN.match(token)
            if match is None:
                raise FrameAncestorsError(
                    f'{token!r} is not allowed. Use \'self\', \'none\', or an exact https origin'
                )
            host = match.group('host')
            if '*' in host:
                raise FrameAncestorsError(f'{token!r} uses a wildcard host')
            if host != host.lower() or len(host) > 253:
                raise FrameAncestorsError(f'{token!r} must be a lowercase host name')
            labels = host.split('.')
            if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels):
                raise FrameAncestorsError(f'{token!r} is not a valid host name')
            port = match.group('port')
            if port is not None and not 1 <= int(port) <= 65535:
                raise FrameAncestorsError(f'{token!r} has an invalid port')
            value = token
        if value not in sources:
            sources.append(value)
    if "'none'" in sources and len(sources) > 1:
        raise FrameAncestorsError("'none' cannot be combined with other sources")
    return sources


def frame_ancestors_sources() -> str | None:
    """CSP source list for hosted ``frame-ancestors``, or None to send no header.

    Unset (empty) means no ``frame-ancestors`` header, which is the behaviour before this
    setting existed. A value that is set is enforced strictly. An invalid value fails the
    ``hosting.E003`` check at startup, and if it reaches a request anyway it fails closed
    to ``'none'``.
    """
    raw = str(getattr(settings, 'HOSTING_FRAME_ANCESTORS', '') or '').strip()
    if not raw:
        return None
    try:
        return ' '.join(parse_frame_ancestors(raw))
    except FrameAncestorsError:
        return "'none'"


def frame_ancestors_denies_all(sources: str | None = None) -> bool:
    value = (sources if sources is not None else frame_ancestors_sources() or '').strip().lower()
    return value == "'none'"


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
            'No identity or admin host is configured for the cookie parent check.',
            hint=(
                'Set HOSTING_COOKIE_PARENT_HOSTS to the identity and admin hostnames, '
                'comma-separated, or set IDENTITY_SERVICE_URL. The startup check compares '
                'their cookie parent with HOSTING_APP_DOMAIN.'
            ),
            id='hosting.E002',
        )
    ]


@register(tags='security')
def frame_ancestors_value_is_safe(app_configs, **kwargs):
    raw = str(getattr(settings, 'HOSTING_FRAME_ANCESTORS', '') or '').strip()
    if not raw:
        return []
    try:
        parse_frame_ancestors(raw)
    except FrameAncestorsError as exc:
        return [
            Error(
                f'HOSTING_FRAME_ANCESTORS is not valid: {exc}.',
                hint=(
                    "Leave it unset to send no frame-ancestors header. Otherwise use 'self', 'none' "
                    'on its own, or exact https origins separated by spaces, '
                    'for example https://shellui.com https://admin.shellui.com.'
                ),
                id='hosting.E003',
            )
        ]
    return []
