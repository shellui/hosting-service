"""Encrypt app environment variable values at rest (Fernet, key from SECRET_KEY)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

_fernet_singleton: Fernet | None = None


def fernet_for_settings() -> Fernet:
    global _fernet_singleton
    if _fernet_singleton is None:
        raw = (getattr(settings, 'SECRET_KEY', '') or '').encode()
        if not raw:
            raise RuntimeError('SECRET_KEY is not configured.')
        digest = hashlib.sha256(raw + b'shellui-hosting-app-env-v1').digest()
        key = base64.urlsafe_b64encode(digest)
        _fernet_singleton = Fernet(key)
    return _fernet_singleton


def encrypt_env_value(plain: str) -> str:
    return fernet_for_settings().encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt_env_value(token: str) -> str:
    try:
        return fernet_for_settings().decrypt(token.encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        raise ValueError('Could not decrypt stored value.') from exc
