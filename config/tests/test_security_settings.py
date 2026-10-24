"""Production security settings validation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from django.core.checks import run_checks
from django.test import Client, TestCase, override_settings
from django.urls import clear_url_caches

from apps.authapi.checks import SECRET_KEY_MIN_LENGTH, secret_key_problem, secret_key_refused_outside_debug


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
            SECRET_KEY='x7' * 30,
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


def _settings_report_env(**env: str) -> dict:
    script = """
import json, os, sys
sys.path.insert(0, %r)
os.environ.setdefault("SECRET_KEY", "test-secret-for-settings-import")
import config.settings as settings
print(json.dumps({
    "SESSION_COOKIE_NAME": settings.SESSION_COOKIE_NAME,
    "CSRF_COOKIE_NAME": settings.CSRF_COOKIE_NAME,
    "CSRF_COOKIE_HTTPONLY": settings.CSRF_COOKIE_HTTPONLY,
    "SESSION_COOKIE_HTTPONLY": settings.SESSION_COOKIE_HTTPONLY,
    "SESSION_COOKIE_DOMAIN": settings.SESSION_COOKIE_DOMAIN,
    "CSRF_COOKIE_DOMAIN": settings.CSRF_COOKIE_DOMAIN,
    "SESSION_COOKIE_SECURE": settings.SESSION_COOKIE_SECURE,
    "CSRF_COOKIE_SECURE": settings.CSRF_COOKIE_SECURE,
    "SESSION_COOKIE_PATH": settings.SESSION_COOKIE_PATH,
    "CSRF_COOKIE_PATH": settings.CSRF_COOKIE_PATH,
}))
""" % (
        str(BASE_DIR),
    )
    merged = os.environ.copy()
    merged.update(env)
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=BASE_DIR,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


_PROD_ENV = {
    'DEBUG': 'false',
    'HOSTING_APP_DOMAIN': 'shellui.app',
    'IDENTITY_ISSUER': 'https://id.shellui.com',
    'IDENTITY_AUDIENCE': 'hosting',
    'IDENTITY_JWKS': '{"keys":[{"kty":"RSA","kid":"k1","n":"x","e":"AQAB","alg":"RS256","use":"sig"}]}',
    'SECRET_KEY': 'ab3XY' * 10,
}


class CookieSettingsTests(unittest.TestCase):
    def test_secure_cookies_use_host_prefix_and_omit_domain(self):
        report = _settings_report_env(**_PROD_ENV)
        self.assertEqual(report['SESSION_COOKIE_NAME'], '__Host-sessionid')
        self.assertEqual(report['CSRF_COOKIE_NAME'], '__Host-csrftoken')
        self.assertTrue(report['SESSION_COOKIE_SECURE'])
        self.assertTrue(report['CSRF_COOKIE_SECURE'])
        self.assertTrue(report['CSRF_COOKIE_HTTPONLY'])
        self.assertTrue(report['SESSION_COOKIE_HTTPONLY'])
        self.assertIsNone(report['SESSION_COOKIE_DOMAIN'])
        self.assertIsNone(report['CSRF_COOKIE_DOMAIN'])
        self.assertEqual(report['SESSION_COOKIE_PATH'], '/')
        self.assertEqual(report['CSRF_COOKIE_PATH'], '/')

    def test_plain_http_keeps_historical_cookie_names(self):
        report = _settings_report_env(
            **_PROD_ENV,
            SESSION_COOKIE_SECURE='false',
            CSRF_COOKIE_SECURE='false',
        )
        self.assertEqual(report['SESSION_COOKIE_NAME'], 'sessionid')
        self.assertEqual(report['CSRF_COOKIE_NAME'], 'csrftoken')
        self.assertFalse(report['SESSION_COOKIE_SECURE'])
        self.assertFalse(report['CSRF_COOKIE_SECURE'])
        self.assertTrue(report['CSRF_COOKIE_HTTPONLY'])
        self.assertIsNone(report['SESSION_COOKIE_DOMAIN'])
        self.assertIsNone(report['CSRF_COOKIE_DOMAIN'])

    def test_debug_http_defaults_are_not_host_prefixed(self):
        report = _settings_report_env(DEBUG='true', SECRET_KEY='ab3XY' * 10)
        self.assertEqual(report['SESSION_COOKIE_NAME'], 'sessionid')
        self.assertEqual(report['CSRF_COOKIE_NAME'], 'csrftoken')
        self.assertTrue(report['CSRF_COOKIE_HTTPONLY'])
        self.assertIsNone(report['CSRF_COOKIE_DOMAIN'])


class SecretKeyCheckTests(unittest.TestCase):
    def test_placeholder_prefix_and_published_example_are_refused(self):
        published = 'django-insecure-12345678901234567890123456789012'
        self.assertIn('placeholder', secret_key_problem(published))
        long_prefix = 'django-insecure-' + ('ab3XY' * 10)
        self.assertIn('placeholder', secret_key_problem(long_prefix))
        self.assertIn(
            'placeholder',
            secret_key_problem('change-me-generate-a-strong-secret-key'),
        )

    def test_empty_and_short_keys_are_refused(self):
        self.assertIn('empty', secret_key_problem(''))
        self.assertIn('empty', secret_key_problem('   '))
        self.assertIn('shorter', secret_key_problem('a' * (SECRET_KEY_MIN_LENGTH - 1)))

    def test_long_generated_key_is_accepted(self):
        self.assertIsNone(secret_key_problem('ab3XY' * 10))

    @override_settings(DEBUG=False, SECRET_KEY='django-insecure-12345678901234567890123456789012')
    def test_registered_check_errors_when_debug_is_false(self):
        errors = [
            item
            for item in run_checks(include_deployment_checks=True)
            if item.id == 'authapi.E005'
        ]
        self.assertEqual(len(errors), 1)
        self.assertIn('placeholder', errors[0].msg)

    @override_settings(DEBUG=False, SECRET_KEY='')
    def test_registered_check_errors_on_empty_key(self):
        errors = secret_key_refused_outside_debug(None)
        self.assertEqual(errors[0].id, 'authapi.E005')
        self.assertIn('empty', errors[0].msg)

    @override_settings(DEBUG=False, SECRET_KEY='ab3XY' * 9)
    def test_registered_check_errors_on_short_key(self):
        errors = secret_key_refused_outside_debug(None)
        self.assertIn('shorter', errors[0].msg)

    @override_settings(DEBUG=True, SECRET_KEY='django-insecure-12345678901234567890123456789012')
    def test_debug_allows_placeholder(self):
        self.assertEqual(secret_key_refused_outside_debug(None), [])

    @override_settings(DEBUG=False, SECRET_KEY='ab3XY' * 10)
    def test_debug_false_accepts_a_long_key(self):
        self.assertEqual(secret_key_refused_outside_debug(None), [])


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
