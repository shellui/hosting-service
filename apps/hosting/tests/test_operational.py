"""Operational APIs: custom domains, environment variables, request logs."""

from __future__ import annotations

import jwt
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.hosting.models import (
    AccessStatus,
    App,
    AppCustomDomain,
    AppEnvironmentVariable,
    CompanyHostingAccess,
    CustomDomainStatus,
    HostedAppRequestLog,
)


def _jwt(
    *,
    user_id: int = 1,
    company_id: int = 10,
    email: str = 'owner@example.com',
    secret: str = 'test-secret',
    is_company_owner: bool = True,
) -> str:
    return jwt.encode(
        {
            'sub': str(user_id),
            'user_id': user_id,
            'company_id': company_id,
            'email': email,
            'user_metadata': {
                'is_staff': False,
                'is_company_owner': is_company_owner,
            },
            'exp': 2**31 - 1,
        },
        secret,
        algorithm='HS256',
    )


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    HOSTING_DEBUG_OPEN=False,
    HOSTING_APP_DOMAIN='apps.example.com',
    HOSTING_REQUEST_LOG_ENABLED=True,
)
class OperationalApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        CompanyHostingAccess.objects.create(company_id=10, status=AccessStatus.APPROVED)
        self.app = App.objects.create(
            name='my-app',
            slug='my-app',
            company_id=10,
            display_name='My App',
        )

    def _auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_jwt()}'}

    def test_custom_domain_lifecycle_and_verified_false(self):
        r = self.client.post(
            f'/hosting/v1/apps/{self.app.slug}/domains',
            {'hostname': 'app.example.org'},
            format='json',
            **self._auth(),
        )
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertFalse(body['verified'])
        self.assertFalse(body['serving'])
        self.assertEqual(body['status'], 'pending_dns')
        self.assertIn('verification_txt_value', body['dns'])

        domain_id = body['id']
        r2 = self.client.post(
            f'/hosting/v1/apps/{self.app.slug}/domains/{domain_id}/refresh',
            **self._auth(),
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['status'], CustomDomainStatus.AWAITING_PLATFORM)

        r3 = self.client.delete(
            f'/hosting/v1/apps/{self.app.slug}/domains/{domain_id}',
            **self._auth(),
        )
        self.assertEqual(r3.status_code, 204)
        self.assertEqual(AppCustomDomain.objects.count(), 0)

    def test_rejects_hostname_on_default_app_domain(self):
        r = self.client.post(
            f'/hosting/v1/apps/{self.app.slug}/domains',
            {'hostname': 'x.apps.example.com'},
            format='json',
            **self._auth(),
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json().get('error'), 'invalid_hostname')

    def test_env_set_list_never_returns_values(self):
        r = self.client.post(
            f'/hosting/v1/apps/{self.app.slug}/environment',
            {'key': 'BUILD_ID', 'value': 'secret-build'},
            format='json',
            **self._auth(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['key'], 'BUILD_ID')
        self.assertTrue(r.json()['value_present'])
        self.assertNotIn('value', r.json())

        r2 = self.client.get(f'/hosting/v1/apps/{self.app.slug}/environment', **self._auth())
        self.assertEqual(r2.status_code, 200)
        rows = r2.json()
        self.assertEqual(len(rows), 1)
        self.assertNotIn('value', rows[0])

        r3 = self.client.get(
            f'/hosting/v1/apps/{self.app.slug}/environment/BUILD_ID',
            **self._auth(),
        )
        self.assertEqual(r3.status_code, 200)
        self.assertNotIn('value', r3.json())

        row = AppEnvironmentVariable.objects.get(app=self.app, key='BUILD_ID')
        self.assertNotEqual(row.value_ciphertext, 'secret-build')

        r4 = self.client.delete(
            f'/hosting/v1/apps/{self.app.slug}/environment/BUILD_ID',
            **self._auth(),
        )
        self.assertEqual(r4.status_code, 204)
        self.assertEqual(AppEnvironmentVariable.objects.count(), 0)

    def test_runtime_logs_unavailable_contract(self):
        r = self.client.get(
            f'/hosting/v1/apps/{self.app.slug}/logs/runtime',
            **self._auth(),
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['source'], 'none')
        self.assertEqual(body['lines'], [])

    def test_request_logs_empty_then_middleware(self):
        r = self.client.get(
            f'/hosting/v1/apps/{self.app.slug}/logs/requests',
            **self._auth(),
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['results'], [])

        from django.test import RequestFactory
        from apps.hosting.middleware import HostedAppRequestLogMiddleware
        from apps.hosting.serve import AppServeView

        req_factory = RequestFactory()
        middleware = HostedAppRequestLogMiddleware(
            lambda request: AppServeView.as_view()(request, path='assets/foo.js')
        )
        request = req_factory.get('/assets/foo.js', HTTP_HOST='my-app.apps.example.com')
        request.request_id = 'rid-1'
        middleware(request)
        self.assertEqual(HostedAppRequestLog.objects.filter(app=self.app).count(), 1)

        r2 = self.client.get(
            f'/hosting/v1/apps/{self.app.slug}/logs/requests?limit=10',
            **self._auth(),
        )
        self.assertEqual(r2.status_code, 200)
        results = r2.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['method'], 'GET')
        self.assertEqual(results[0]['request_id'], 'rid-1')

    def test_deploy_token_blocked(self):
        from apps.hosting.deploy_tokens import create_deploy_token

        _token, raw = create_deploy_token(company_id=10, name='ci', created_by_id=1)
        response = self.client.get(
            f'/hosting/v1/apps/{self.app.slug}/domains',
            HTTP_AUTHORIZATION=f'Bearer {raw}',
        )
        self.assertEqual(response.status_code, 403)
