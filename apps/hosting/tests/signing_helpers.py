"""Test RS256 keys for service assertions and Identity agent tokens."""

from __future__ import annotations

import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
MCP_SIGNING_TEST_SETTINGS = {
    'MCP_SIGNING_KEY_PEM': _KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode(),
    'MCP_SIGNING_ISSUER': 'https://hosting.test',
}

MCP_IDENTITY_ISSUER = 'https://identity.test'
MCP_IDENTITY_KID = 'test-identity'
_IDENTITY_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mcp_identity_private_key():
    return _IDENTITY_KEY


def mcp_identity_signing_jwk():
    """PyJWK the hosting JWT client can use to verify test agent tokens."""
    from jwt import PyJWK

    return PyJWK.from_dict(mcp_identity_jwks()['keys'][0])


def mcp_identity_jwks() -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(_IDENTITY_KEY.public_key()))
    jwk.update({'kid': MCP_IDENTITY_KID, 'use': 'sig', 'alg': 'RS256'})
    return {'keys': [jwk]}


MCP_IDENTITY_TEST_SETTINGS = {
    'IDENTITY_ISSUER': MCP_IDENTITY_ISSUER,
    'IDENTITY_JWKS_DOCUMENT': mcp_identity_jwks(),
}
