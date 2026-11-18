"""Revocation lists are verified with the configured JWKS source."""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from apps.hosting.mcp_identity import _revocation_verify_kwargs


class RevocationJwksSourceTests(SimpleTestCase):
    @override_settings(IDENTITY_JWKS_DOCUMENT=None, IDENTITY_JWKS_URL='http://identity:8000/.well-known/jwks.json')
    def test_uses_identity_jwks_url_without_pinned_document(self):
        kwargs = _revocation_verify_kwargs('http://localhost:8001')
        self.assertEqual(kwargs['expected_issuer'], 'http://localhost:8001')
        self.assertEqual(kwargs['identity_jwks_url'], 'http://identity:8000/.well-known/jwks.json')
        self.assertNotIn('jwks', kwargs)

    @override_settings(IDENTITY_JWKS_DOCUMENT={'keys': [{'kid': 'k'}]}, IDENTITY_JWKS_URL='http://identity:8000/x')
    def test_pinned_document_wins(self):
        kwargs = _revocation_verify_kwargs('http://localhost:8001')
        self.assertEqual(kwargs['jwks'], {'keys': [{'kid': 'k'}]})
        self.assertNotIn('identity_jwks_url', kwargs)
