"""CORS: preview origins must be allowed without per-slug env entries."""

import os
import subprocess
import sys
from pathlib import Path

from django.test import Client, TestCase, override_settings

BASE_DIR = Path(__file__).resolve().parents[2]


@override_settings(CORS_ALLOW_ALL_ORIGINS=True, CORS_ALLOW_CREDENTIALS=False)
class PermissiveCorsTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_preflight_allows_random_hosting_preview_origin(self):
        origin = 'https://vpzzsxvzsmp7.shellui.app'
        response = self.client.options(
            '/hosting/v1/health',
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='authorization',
        )
        self.assertEqual(response.status_code, 200)
        # django-cors-headers echoes * when allow-all + no credentials.
        self.assertEqual(response['Access-Control-Allow-Origin'], '*')

    def test_get_exposes_acao_for_preview_origin(self):
        origin = 'https://abcd1234efgh.shellui.app'
        response = self.client.get('/hosting/v1/health', HTTP_ORIGIN=origin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Access-Control-Allow-Origin'], '*')


class CorsCredentialsStartupTests(TestCase):
    def test_allow_all_with_credentials_fails_at_import(self):
        script = """
import os, sys
sys.path.insert(0, %r)
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ["DEBUG"] = "true"
os.environ["CORS_ALLOW_ALL_ORIGINS"] = "true"
os.environ["CORS_ALLOW_CREDENTIALS"] = "true"
try:
    import config.settings
except Exception as exc:
    print(str(exc))
    sys.exit(0)
sys.exit(1)
""" % (
            str(BASE_DIR),
        )
        result = subprocess.run(
            [sys.executable, '-c', script],
            cwd=BASE_DIR,
            env={**os.environ, 'SECRET_KEY': 'test-secret'},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('CORS_ALLOW_ALL_ORIGINS', result.stdout)
