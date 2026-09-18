"""Relative path validation for artifact extract and static serving."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote

from django.http import Http404

_ENCODED_DOTDOT = re.compile(r'(?i)(?:^|[/%5c])(?:%2e%2e|\.\.)(?:$|[/%5c])')
_WINDOWS_ABSOLUTE = re.compile(r'(?i)^[a-z]:[/\\]')


def normalize_relative_path(path: str) -> str | None:
    """
    Normalize a relative path for storage keys.

    Returns ``None`` for empty, absolute, or traversal paths.
    """
    if path is None:
        return None
    if _WINDOWS_ABSOLUTE.match(path or ''):
        return None
    slash = path.replace('\\', '/').strip('/')
    if not slash:
        return None
    parts = slash.split('/')
    if any(part in {'', '..'} for part in parts):
        return None
    normalized = posixpath.normpath(slash)
    if not normalized or normalized == '.':
        return None
    if normalized.startswith('../') or normalized == '..':
        return None
    if any(part == '..' for part in normalized.split('/')):
        return None
    return normalized


def raw_path_has_traversal(path: str) -> bool:
    """Detect literal or encoded ``..`` segments before storage access."""
    raw = path or ''
    if '..' in raw:
        return True
    if _ENCODED_DOTDOT.search(raw):
        return True
    for segment in raw.replace('\\', '/').split('/'):
        if not segment:
            continue
        if unquote(segment) == '..':
            return True
    return False


def validate_serve_path(path: str) -> str:
    """Return a safe relative path or raise ``Http404``."""
    raw = path or ''
    if not raw.strip('/'):
        return ''
    if raw_path_has_traversal(raw):
        raise Http404('Invalid path')
    decoded = unquote(raw)
    rel = normalize_relative_path(decoded)
    if rel is None:
        raise Http404('Invalid path')
    return rel
