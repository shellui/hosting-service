"""Rate limits on deploy/upload/finalize and related endpoints."""

from __future__ import annotations

from unittest.mock import patch

import jwt
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, Deployment


def _token(*, user_id: int = 1, company_id: int = 10) -> str:
    return jwt.encode(
        {
            'sub': str(user_id),
            'user_id': user_id,
            'company_id': company_id,
            'email': 'user@example.com',
            'user_metadata': {'is_staff': False, 'is_company_owner': False},
            'exp': 2**31 - 1,
        },
        'test-secret',
        algorithm='HS256',
    )


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    HOSTING_DEBUG_OPEN=True,
    HOSTING_RATE_LIMIT_ENABLED=True,
    HOSTING_RATE_LIMITS={
        'deploy': {'limit': 2, 'window': 60},
        'upload': {'limit': 2, 'window': 60},
        'destructive': {'limit': 2, 'window': 60},
        'access_request': {'limit': 2, 'window': 300},
    },
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'rate-limit-tests',
        }
    },
)
class HostingRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.jwks_patch = patch('apps.authapi.authentication.get_jwks_client')
        mock_client = self.jwks_patch.start()
        jwks = mock_client.return_value
        jwks.get_signing_key.return_value = None
        jwks.key_count.return_value = 0
        jwks.key_ids.return_value = []
        self.addCleanup(self.jwks_patch.stop)
        CompanyHostingAccess.objects.create(company_id=10, status=AccessStatus.APPROVED)
        self.auth = f'Bearer {_token()}'

    def test_preview_deploy_rate_limited(self):
        url = '/hosting/v1/preview'
        payload = {
            'display_name': 'Demo',
            'app_version': '1.0.0',
            'shellui_version': '0.5.0',
        }
        for _ in range(2):
            response = self.client.post(url, payload, HTTP_AUTHORIZATION=self.auth)
            self.assertEqual(response.status_code, 201, response.content)
        response = self.client.post(url, payload, HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '60')

    def test_finalize_rate_limited(self):
        app = App.objects.create(
            company_id=10,
            name='demo',
            slug='demoslug01',
            display_name='Demo',
            created_by_id=1,
        )
        deployments = []
        for i in range(3):
            deployments.append(
                Deployment.objects.create(
                    app=app,
                    app_version=f'1.0.{i}',
                    shellui_version='0.5.0',
                    deployed_by_id=1,
                    status='draft',
                )
            )
        url_base = f'/hosting/v1/apps/{app.slug}/deployments'
        for dep in deployments[:2]:
            dep.status = 'uploaded'
            dep.save(update_fields=['status'])
            response = self.client.post(
                f'{url_base}/{dep.id}/finalize',
                HTTP_AUTHORIZATION=self.auth,
            )
            self.assertIn(response.status_code, {200, 400, 409}, response.content)
        dep = deployments[2]
        dep.status = 'uploaded'
        dep.save(update_fields=['status'])
        response = self.client.post(
            f'{url_base}/{dep.id}/finalize',
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 429)
