"""Tests for identity oauth-redirect sync client."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.hosting.identity_redirects import (
    app_origin_for_sync,
    delete_hosting_oauth_redirect_origin,
    upsert_hosting_oauth_redirect,
)


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

    @override_settings(IDENTITY_SERVICE_URL='')
    @patch('apps.hosting.identity_redirects.requests.put')
    def test_upsert_noop_when_unconfigured(self, put):
        upsert_hosting_oauth_redirect(_FakeApp(), access_token='user-jwt')
        put.assert_not_called()

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
