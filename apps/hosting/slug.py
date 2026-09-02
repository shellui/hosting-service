"""App name and public URL slug helpers."""

from __future__ import annotations

import re
import secrets
import string

SLUG_PATTERN = re.compile(r'^[a-z][a-z0-9-]{2,62}$')
APP_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9-]{2,62}$')
PUBLIC_SLUG_LENGTH = 12
PUBLIC_SLUG_ALPHABET = string.ascii_lowercase + string.digits

RESERVED_SLUGS = frozenset(
    {
        'admin',
        'api',
        'apps',
        'health',
        'hosting',
        'stats',
        'access',
        'deployments',
        'preview',
    }
)


def validate_app_name(value: str) -> str:
    """Company-scoped app identifier from shellui config (`hosting.app`)."""
    name = (value or '').strip().lower()
    if not APP_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            'App name must be 3–63 characters, start with a letter, and contain only '
            'lowercase letters, digits, and hyphens.'
        )
    if name in RESERVED_SLUGS:
        raise ValueError(f'App name {name!r} is reserved.')
    return name


def validate_slug(value: str) -> str:
    slug = (value or '').strip().lower()
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(
            'Slug must be 3–63 characters, start with a letter, and contain only '
            'lowercase letters, digits, and hyphens.'
        )
    if slug in RESERVED_SLUGS:
        raise ValueError(f'Slug {slug!r} is reserved.')
    return slug


def generate_public_slug(*, exists) -> str:
    """Generate a globally unique public URL slug (not user-chosen)."""
    for _ in range(32):
        first = secrets.choice(string.ascii_lowercase)
        rest = ''.join(
            secrets.choice(PUBLIC_SLUG_ALPHABET) for _ in range(PUBLIC_SLUG_LENGTH - 1)
        )
        candidate = f'{first}{rest}'
        if not exists(candidate):
            return candidate
    raise RuntimeError('Could not generate a unique public slug.')
