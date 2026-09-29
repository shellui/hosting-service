"""Standard Webhooks-style HMAC signing for outbound payloads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
import uuid


def generate_whsec_secret() -> str:
    """Return a new ``whsec_<base64>`` signing secret (32 random bytes)."""
    return f'whsec_{base64.b64encode(secrets.token_bytes(32)).decode("ascii")}'


def signing_secret_key(secret: str) -> bytes:
    """
    HMAC key bytes for ``secret``.

    ``whsec_<base64>`` decodes the suffix (Standard Webhooks / n8n style). Plain strings
    use UTF-8 bytes unchanged.
    """
    raw = (secret or '').strip()
    if raw.startswith('whsec_'):
        encoded = raw[len('whsec_') :]
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError('Invalid whsec_ signing secret (bad base64).') from exc
    return raw.encode('utf-8')


def sign_webhook_body(*, secret: str, body: bytes, webhook_id: str | None = None) -> dict[str, str]:
    """
    Return headers: ``webhook-id``, ``webhook-timestamp``, ``webhook-signature``.

    Signature format: ``v1,<base64(hmac_sha256)>`` over ``{id}.{timestamp}.{body}``.
    """
    key = signing_secret_key(secret)
    wid = webhook_id or str(uuid.uuid4())
    ts = str(int(time.time()))
    signed_content = f'{wid}.{ts}.'.encode('utf-8') + body
    digest = hmac.new(key, signed_content, hashlib.sha256).digest()
    sig = base64.b64encode(digest).decode('ascii')
    return {
        'webhook-id': wid,
        'webhook-timestamp': ts,
        'webhook-signature': f'v1,{sig}',
    }
