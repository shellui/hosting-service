"""Tests for Prometheus metrics endpoints."""

from __future__ import annotations

from unittest.mock import patch

import jwt
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, Deployment, DeploymentStatus


def make_token(
    *,
    user_id: int = 1,
    company_id: int = 10,
    email: str = 'user@example.com',
    is_staff: bool = False,
    is_company_owner: bool = False,
    access_global_metrics: bool = False,
    secret: str = 'test-secret',
) -> str:
    payload = {
        'sub': str(user_id),
        'user_id': user_id,
        'company_id': company_id,
        'email': email,
        'user_metadata': {
            'is_staff': is_staff,
            'is_company_owner': is_company_owner,
        },
        'exp': 2**31 - 1,
    }
    if access_global_metrics:
        payload['pat_agm'] = True
    return jwt.encode(payload, secret, algorithm='HS256')


def _seed_company(*, company_id: int, name: str, artifact_size: int = 100) -> App:
    CompanyHostingAccess.objects.get_or_create(
        company_id=company_id,
        defaults={'status': AccessStatus.APPROVED},
    )
    app = App.objects.create(
        name=name,
        slug=f'{name}-slug',
        company_id=company_id,
        display_name=name.title(),
        created_by_id=1,
    )
    Deployment.objects.create(
        app=app,
        app_version='1.0.0',
        shellui_version='0.5.0',
        status=DeploymentStatus.ACTIVE,
        storage_prefix=f'co/{company_id}/{app.id}/1.0.0',
        artifact_size=artifact_size,
        finalized_at=timezone.now(),
    )
    return app


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
)
class HostingMetricsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.jwks_patch = patch('apps.authapi.authentication.get_jwks_client')
        mock_client = self.jwks_patch.start()
        mock_client.return_value.get_signing_key.return_value = None
        self.addCleanup(self.jwks_patch.stop)

    def _auth(self, **kwargs):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(**kwargs)}'}

    def test_metrics_requires_auth(self):
        response = self.client.get('/hosting/v1/metrics')
        self.assertEqual(response.status_code, 401)

    def test_metrics_forbidden_for_regular_member(self):
        _seed_company(company_id=10, name='demo')
        response = self.client.get('/hosting/v1/metrics', **self._auth())
        self.assertEqual(response.status_code, 403)

    def test_metrics_company_owner_sees_only_own_company(self):
        _seed_company(company_id=10, name='alpha', artifact_size=50)
        _seed_company(company_id=11, name='beta', artifact_size=200)

        response = self.client.get(
            '/hosting/v1/metrics',
            HTTP_ACCEPT='text/plain',
            **self._auth(is_company_owner=True),
        )
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        self.assertIn('shellui_hosting_apps_total{company_id="10"}', text)
        self.assertNotIn('company_id="11"', text)
        self.assertIn('shellui_hosting_apps_total{company_id="10"} 1.0', text)
        self.assertIn('shellui_hosting_artifact_bytes{company_id="10"} 50.0', text)

    def test_metrics_rejects_company_id_query(self):
        response = self.client.get(
            '/hosting/v1/metrics?company_id=10',
            **self._auth(is_company_owner=True),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('query string', response.content.decode())

    def test_metrics_staff_ok(self):
        _seed_company(company_id=10, name='demo')
        response = self.client.get('/hosting/v1/metrics', **self._auth(is_staff=True))
        self.assertEqual(response.status_code, 200)
        self.assertIn('shellui_hosting_deployments_total{company_id="10"}', response.content.decode())

    def test_metrics_all_staff_includes_every_company(self):
        _seed_company(company_id=10, name='alpha')
        _seed_company(company_id=11, name='beta')
        response = self.client.get('/hosting/v1/metrics/all', **self._auth(is_staff=True))
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        self.assertIn('company_id="10"', text)
        self.assertIn('company_id="11"', text)

    def test_metrics_all_forbidden_for_owner(self):
        response = self.client.get('/hosting/v1/metrics/all', **self._auth(is_company_owner=True))
        self.assertEqual(response.status_code, 403)

    def test_metrics_all_pat_agm(self):
        _seed_company(company_id=10, name='demo')
        response = self.client.get(
            '/hosting/v1/metrics/all',
            **self._auth(is_company_owner=True, access_global_metrics=True),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('shellui_hosting_apps_total', response.content.decode())
