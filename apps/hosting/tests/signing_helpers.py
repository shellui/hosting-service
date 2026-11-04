"""Test RS256 key this service signs internal MCP assertions with (config/service_signing.py)."""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
MCP_SIGNING_TEST_SETTINGS = {
    'MCP_SIGNING_KEY_PEM': _KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode(),
    'MCP_SIGNING_ISSUER': 'https://hosting.test',
}
