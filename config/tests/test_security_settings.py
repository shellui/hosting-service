"""Production security settings validation."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from django.test import Client, TestCase, override_settings
from django.urls import clear_url_caches


BASE_DIR = Path(__file__).resolve().parents[2]


def _settings_import_env(**env: str) -> subprocess.CompletedProcess:
    """Import config.settings in a subprocess with the given env overrides."""
    script = """
import os, sys
sys.path.insert(0, %r)
os.environ.setdefault("SECRET_KEY", "test-secret-for-settings-import")
try:
    import config.settings  # noqa: F401
except Exception as exc:
    print(type(exc).__name__ + ": " + str(exc))
    sys.exit(1)
print("OK")
""" % (
        str(BASE_DIR),
    )
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        [sys.executable, '-c', script],
        cwd=BASE_DIR,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )


class ProductionSettingsValidationTests(unittest.TestCase):
    def test_prod_requires_issuer_audience_and_pinned_jwks(self):
        result = _settings_import_env(
            DEBUG='false',
            HOSTING_APP_DOMAIN='shellui.app',
        )
        self.assertNotEqual(result.returncode, 0)
        combined = (result.stdout + result.stderr).lower()
        self.assertIn('identity_issuer', combined)
        self.assertIn('identity_audience', combined)
        self.assertIn('jwks', combined)

    def test_prod_accepts_pinned_jwks_with_iss_aud(self):
        result = _settings_import_env(
            DEBUG='false',
            HOSTING_APP_DOMAIN='shellui.app',
            IDENTITY_ISSUER='https://id.shellui.com',
            IDENTITY_AUDIENCE='hosting',
            IDENTITY_JWKS='{"keys":[{"kty":"RSA","kid":"k1","n":"x","e":"AQAB","alg":"RS256","use":"sig"}]}',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hosting_debug_open_rejected_in_production(self):
        result = _settings_import_env(
            DEBUG='false',
            HOSTING_APP_DOMAIN='shellui.app',
            HOSTING_DEBUG_OPEN='true',
            IDENTITY_ISSUER='https://id.shellui.com',
            IDENTITY_AUDIENCE='hosting',
            IDENTITY_JWKS='{"keys":[{"kty":"RSA","kid":"k1","n":"x","e":"AQAB","alg":"RS256","use":"sig"}]}',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HOSTING_DEBUG_OPEN', result.stdout + result.stderr)

    def test_cors_allow_all_with_credentials_rejected(self):
        result = _settings_import_env(
            DEBUG='true',
            CORS_ALLOW_ALL_ORIGINS='true',
            CORS_ALLOW_CREDENTIALS='true',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CORS_ALLOW_ALL_ORIGINS', result.stdout + result.stderr)


@override_settings(DJANGO_ADMIN_ENABLED=False)
class AdminEnabledUrlTests(TestCase):
    def test_admin_not_mounted_when_disabled(self):
        from importlib import reload

        import config.urls as urls_module

        reload(urls_module)
        clear_url_caches()
        try:
            response = Client().get('/admin/')
            self.assertEqual(response.status_code, 404)
        finally:
            with override_settings(DJANGO_ADMIN_ENABLED=True):
                reload(urls_module)
                clear_url_caches()
