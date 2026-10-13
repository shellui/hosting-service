"""Tests for identity oauth-redirect sync client."""

from unittest.mock import MagicMock, patch

import jwt
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.hosting.identity_redirects import (
    app_origin_for_sync,
    delete_hosting_oauth_redirect_origin,
    upsert_hosting_oauth_redirect,
)
from apps.hosting.services import create_deployment, create_preview_app


class _FakeApp:
    def __init__(self, *, slug='demo', company_id=7, display_name='Demo'):
        self.slug = slug
        self.company_id = company_id
        self.display_name = display_name


class IdentityRedirectSyncTests(SimpleTestCase):
    @override_settings(
        HOSTING_APP_DOMAIN='shellui.app',
        HOSTING_APP_SCHEME='https',
    )
    def test_app_origin_for_sync(self):
        self.assertEqual(app_origin_for_sync(_FakeApp()), 'https://demo.shellui.app')

    @override_settings(
        IDENTITY_SERVICE_URL='',
        IDENTITY_JWKS_URL='http://localhost:8000/.well-known/jwks.json',
    )
    @patch('apps.hosting.identity_redirects.requests.put')
    def test_upsert_noop_when_unconfigured(self, put):
        upsert_hosting_oauth_redirect(_FakeApp(), access_token='user-jwt')
        put.assert_not_called()

    @override_settings(
        IDENTITY_SERVICE_URL='https://id.shellui.com',
        IDENTITY_SYNC_TIMEOUT=5,
        HOSTING_APP_DOMAIN='shellui.app',
        HOSTING_APP_SCHEME='https',
    )
    @patch('apps.hosting.identity_redirects.requests.put')
    def test_upsert_retries_server_errors_not_client_errors(self, put):
        put.side_effect = [
            MagicMock(status_code=503, text='unavailable'),
            MagicMock(status_code=201, text=''),
        ]
        self.assertTrue(upsert_hosting_oauth_redirect(_FakeApp(), access_token='user-jwt'))
        self.assertEqual(put.call_count, 2)

        put.reset_mock()
        put.side_effect = None
        put.return_value = MagicMock(
            status_code=403,
            text='{"error": "Forbidden"}',
            json=lambda: {'error': 'Forbidden'},
        )
        failed = upsert_hosting_oauth_redirect(_FakeApp(), access_token='user-jwt')
        self.assertFalse(failed)
        self.assertIn('Forbidden', failed.warning)
        self.assertIn('company owner or staff', failed.warning)
        put.assert_called_once()

    @override_settings(IDENTITY_SERVICE_URL='http://identity.test')
    @patch('apps.hosting.identity_redirects.requests.put')
    def test_upsert_noop_without_user_token(self, put):
        upsert_hosting_oauth_redirect(_FakeApp(), access_token=None)
        put.assert_not_called()

    @override_settings(
        IDENTITY_SERVICE_URL='http://identity.test',
        IDENTITY_SYNC_TIMEOUT=5,
        HOSTING_APP_DOMAIN='shellui.app',
        HOSTING_APP_SCHEME='https',
    )
    @patch('apps.hosting.identity_redirects.requests.put')
    def test_upsert_calls_identity_with_user_jwt(self, put):
        put.return_value = MagicMock(status_code=201, text='')
        upsert_hosting_oauth_redirect(_FakeApp(display_name='My preview'), access_token='user-jwt')
        put.assert_called_once()
        args, kwargs = put.call_args
        self.assertEqual(args[0], 'http://identity.test/api/v1/hosting-oauth-redirects')
        self.assertEqual(kwargs['json']['base_url'], 'https://demo.shellui.app')
        self.assertEqual(kwargs['json']['label'], 'My preview')
        self.assertNotIn('company_id', kwargs['json'])
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer user-jwt')

    @override_settings(
        IDENTITY_SERVICE_URL='http://identity.test',
        IDENTITY_SYNC_TIMEOUT=5,
    )
    @patch('apps.hosting.identity_redirects.requests.delete')
    def test_delete_calls_identity_with_user_jwt(self, delete):
        delete.return_value = MagicMock(status_code=204, text='')
        delete_hosting_oauth_redirect_origin(
            origin='https://demo.shellui.app',
            access_token='user-jwt',
        )
        delete.assert_called_once()
        args, kwargs = delete.call_args
        self.assertEqual(args[0], 'http://identity.test/api/v1/hosting-oauth-redirects')
        self.assertEqual(kwargs['json']['base_url'], 'https://demo.shellui.app')
        self.assertNotIn('company_id', kwargs['json'])
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer user-jwt')


def _access_token(*, company_id: int, user_id: int = 10) -> str:
    return jwt.encode(
        {
            'sub': str(user_id),
            'user_id': user_id,
            'company_id': company_id,
            'email': 'owner@example.com',
            'exp': 2**31 - 1,
        },
        'test-secret',
        algorithm='HS256',
    )


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_SOURCE='env',
    IDENTITY_JWKS_URL='https://id.shellui.com/.well-known/jwks.json',
    IDENTITY_SERVICE_URL='https://id.shellui.com',
    HOSTING_DEBUG_OPEN=True,
    HOSTING_APP_DOMAIN='shellui.app',
    HOSTING_APP_SCHEME='https',
    IDENTITY_SYNC_TIMEOUT=5,
)
class PreviewDeployRegistersOAuthRedirectTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        patcher = patch('apps.authapi.authentication.get_jwks_client')
        mock_client = patcher.start()
        mock_client.return_value.get_signing_key.return_value = None
        self.addCleanup(patcher.stop)

    @patch('apps.hosting.identity_redirects.requests.put')
    def test_preview_deploy_registers_origin_and_reports_it(self, put):
        put.return_value = MagicMock(status_code=201, text='', json=lambda: {})
        token = _access_token(company_id=2)
        response = self.client.post(
            '/hosting/v1/preview',
            {
                'display_name': 'Demo',
                'app_version': '1.0.0',
                'shellui_version': '0.6.1',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        slug = body['slug']
        put.assert_called_once()
        args, kwargs = put.call_args
        self.assertEqual(args[0], 'https://id.shellui.com/api/v1/hosting-oauth-redirects')
        self.assertEqual(kwargs['json']['base_url'], f'https://{slug}.shellui.app')
        self.assertNotIn('company_id', kwargs['json'])
        self.assertEqual(kwargs['headers']['Authorization'], f'Bearer {token}')
        self.assertIs(body['oauth_redirect_registered'], True)
        self.assertEqual(body['oauth_redirect_origin'], f'https://{slug}.shellui.app')
        self.assertNotIn('oauth_redirect_warning', body)

    @patch('apps.hosting.identity_redirects.requests.put')
    def test_preview_deploy_reports_identity_rejection(self, put):
        put.return_value = MagicMock(
            status_code=403,
            text='{"error": "Forbidden"}',
            json=lambda: {'error': 'Forbidden'},
        )
        token = _access_token(company_id=2)
        response = self.client.post(
            '/hosting/v1/preview',
            {
                'display_name': 'Demo',
                'app_version': '1.0.0',
                'shellui_version': '0.6.1',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertIs(body['oauth_redirect_registered'], False)
        self.assertIn('Forbidden', body['oauth_redirect_warning'])
        self.assertTrue(body['oauth_redirect_origin'].endswith('.shellui.app'))

    @patch('apps.hosting.services._activate_deployment', side_effect=lambda **kwargs: kwargs['deployment'])
    @patch('apps.hosting.identity_redirects.requests.put')
    def test_finalize_reports_identity_rejection(self, put, _activate):
        put.return_value = MagicMock(
            status_code=403,
            text='{"error": "Forbidden"}',
            json=lambda: {'error': 'Forbidden'},
        )
        app = create_preview_app(company_id=2, user_id=10, display_name='Demo')
        deployment = create_deployment(
            app=app,
            app_version='1.0.0',
            shellui_version='0.6.1',
            deployed_by_id=10,
        )
        token = _access_token(company_id=2)
        response = self.client.post(
            f'/hosting/v1/apps/{app.slug}/deployments/{deployment.id}/finalize',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertIs(body['oauth_redirect_registered'], False)
        self.assertEqual(body['oauth_redirect_origin'], f'https://{app.slug}.shellui.app')
        self.assertIn('Forbidden', body['oauth_redirect_warning'])
        put.assert_called_once()
        self.assertEqual(put.call_args.kwargs['headers']['Authorization'], f'Bearer {token}')


@override_settings(
    IDENTITY_SERVICE_URL='',
    IDENTITY_JWKS_URL='http://localhost:8000/.well-known/jwks.json',
    HOSTING_DEBUG_OPEN=True,
    HOSTING_APP_DOMAIN='shellui.app',
    HOSTING_APP_SCHEME='https',
)
class SyncOAuthRedirectsCommandTests(TestCase):
    @patch('apps.hosting.management.commands.sync_oauth_redirects.upsert_hosting_oauth_redirect', return_value=True)
    def test_syncs_only_the_token_company(self, upsert):
        create_preview_app(company_id=2, user_id=10, display_name='Mine')
        create_preview_app(company_id=9, user_id=10, display_name='Other')
        token = _access_token(company_id=2)
        call_command('sync_oauth_redirects', access_token=token)
        self.assertEqual(upsert.call_count, 1)
        app = upsert.call_args.args[0]
        self.assertEqual(app.company_id, 2)
        self.assertEqual(upsert.call_args.kwargs['access_token'], token)

    def test_rejects_company_id_mismatch(self):
        token = _access_token(company_id=2)
        with self.assertRaises(CommandError):
            call_command('sync_oauth_redirects', access_token=token, company_id=9)
