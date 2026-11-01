"""Shellui MCP endpoint and OpenAPI exposure."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import jwt
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from shellui_mcp.internal import InternalAssertionError

from apps.hosting.mcp_revocation import _agents_cache_key, _cache_key, _unavailable_key


def _clear_revocation_cache(company_id: int = 42) -> None:
    from django.core.cache import cache

    for cid in (None, company_id):
        cache.delete(_cache_key(cid))
        cache.delete(_unavailable_key(cid))
        cache.delete(_agents_cache_key(cid))


def _agent_token(
    *,
    secret: str = 'test-secret',
    agent_id: str | None = None,
    company_id: int = 42,
    mcp_access: str = 'read_only',
    mcp_destructive: bool = False,
    scope: str = 'hosting',
    aud: str | list[str] = 'http://127.0.0.1/mcp',
) -> str:
    agent_id = agent_id or str(uuid.uuid4())
    return jwt.encode(
        {
            'sub': f'agent:{agent_id}',
            'agent_id': agent_id,
            'company_id': company_id,
            'scope': scope,
            'mcp_access': mcp_access,
            'mcp_read': 'safe',
            'mcp_destructive': mcp_destructive,
            'aud': aud,
            'exp': 2**31 - 1,
        },
        secret,
        algorithm='HS256',
    )


@override_settings(
    DEBUG=True,
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_AUDIENCE='',
    IDENTITY_ISSUER='',
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    HOSTING_MCP_RESOURCE='http://127.0.0.1/mcp',
)
class McpEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.agent_id = str(uuid.uuid4())
        self.token = _agent_token(agent_id=self.agent_id)
        _clear_revocation_cache(42)
        self._revocation_ok = patch(
            'apps.hosting.mcp_revocation.fetch_revocation_payload',
            return_value={'revoked_agent_ids': []},
        )
        self._revocation_ok.start()
        from apps.hosting import mcp_views

        mcp_views._server = None

    def tearDown(self):
        self._revocation_ok.stop()

    def _rpc(self, method: str, params: dict | None = None, *, token: str | None = None):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}
        return self.client.post(
            reverse('mcp'),
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token or self.token}',
        )

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_tools_list_excludes_internal_and_untagged(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        response = self._rpc('tools/list')
        self.assertEqual(response.status_code, 200)
        tools = response.json()['result']['tools']
        names = {t['name'] for t in tools}
        self.assertIn('hosting_v1_apps_list', names)
        self.assertNotIn('hosting_v1_deploy_tokens_create', names)
        self.assertNotIn('hosting_v1_health_retrieve', names)
        self.assertNotIn('api_v1_internal_company_deletions_create', names)
        self.assertNotIn('hosting_v1_apps_deployments_upload_update', names)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_wrong_service_scope_forbidden(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        token = _agent_token(scope='email')
        response = self._rpc('tools/list', token=token)
        self.assertEqual(response.status_code, 403)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_resource_audience_accepted(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        token = _agent_token(aud='http://127.0.0.1/mcp')
        response = self._rpc('tools/list', token=token)
        self.assertEqual(response.status_code, 200)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_staff_user_jwt_refused_on_mcp(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        token = jwt.encode(
            {
                'sub': '99',
                'user_id': 99,
                'company_id': 42,
                'exp': 2**31 - 1,
                'user_metadata': {'is_staff': True, 'is_company_owner': False},
            },
            'test-secret',
            algorithm='HS256',
        )
        response = self._rpc('tools/list', token=token)
        self.assertEqual(response.status_code, 401)

    @patch('apps.authapi.authentication.get_jwks_client')
    @override_settings(
        HOSTING_MCP_RESOURCE='',
        HOSTING_PUBLIC_URL='https://hosting.example.com',
    )
    def test_public_url_resource_aud_before_request_host(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        token = _agent_token(aud='https://hosting.example.com/mcp')
        response = self._rpc('tools/list', token=token)
        self.assertEqual(response.status_code, 200)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_agent_cannot_create_deploy_token_via_api(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        token = _agent_token(mcp_access='full')
        response = self.client.post(
            '/hosting/v1/deploy-tokens',
            data={'name': 'ci'},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body.get('error') or body.get('detail'), 'forbidden')

    @patch('apps.authapi.authentication.get_jwks_client')
    @override_settings(IDENTITY_SERVICE_URL='http://identity.test')
    @patch('apps.hosting.mcp_identity.parse_trusted_revocation_poll_response', side_effect=InternalAssertionError('Invalid'))
    @patch('apps.hosting.mcp_identity.requests.get')
    @patch('apps.hosting.mcp_identity.build_mcp_revocation_assertion', return_value='rev-assertion')
    def test_revocation_list_bad_signature_fail_closed(self, _mock_assert, mock_get, _mock_trusted, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        self._revocation_ok.stop()
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'revoked_agent_ids': [],
            'revocation_assertion': 'bad-signature',
        }
        mock_get.return_value.raise_for_status = lambda: None
        _clear_revocation_cache(42)
        response = self._rpc('tools/list')
        self._revocation_ok.start()
        self.assertEqual(response.status_code, 403)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_legacy_shared_audience_rejected(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        token = _agent_token(aud='shellui-mcp')
        response = self._rpc('tools/list', token=token)
        self.assertEqual(response.status_code, 401)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_revocation_poll_failure_denies_mcp(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        self._revocation_ok.stop()
        with patch('apps.hosting.mcp_revocation.fetch_revocation_payload', return_value=None):
            response = self._rpc('tools/list')
        self._revocation_ok.start()
        self.assertEqual(response.status_code, 403)

    @patch('apps.authapi.authentication.get_jwks_client')
    @override_settings(IDENTITY_SERVICE_URL='http://identity.test')
    @patch('apps.hosting.mcp_identity.parse_trusted_revocation_poll_response', return_value=(frozenset(), 30, []))
    @patch('apps.hosting.mcp_identity.build_mcp_revocation_assertion', return_value='signed-revocation-assertion')
    @patch('apps.hosting.mcp_identity.requests.get')
    def test_revocation_poll_sends_signed_assertion(self, mock_get, _mock_assertion, _mock_trusted, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'revoked_agent_ids': []}
        mock_get.return_value.raise_for_status = lambda: None
        from apps.hosting.mcp_identity import fetch_revocation_payload

        fetch_revocation_payload()
        mock_get.assert_called_once()
        headers = mock_get.call_args.kwargs.get('headers') or {}
        self.assertEqual(headers.get('Authorization'), 'Bearer signed-revocation-assertion')

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_revoked_agent_refused(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        from django.core.cache import cache

        from django.core.cache import cache

        cache.set(_cache_key(42), [self.agent_id], timeout=60)
        with patch('apps.hosting.mcp_revocation.blocked_agent_ids', return_value={self.agent_id}):
            response = self._rpc('tools/list')
        self.assertEqual(response.status_code, 403)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_read_only_blocks_writes(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        response = self._rpc(
            'tools/call',
            {
                'name': 'hosting_v1_preview_create',
                'arguments': {
                    'path': '/hosting/v1/preview',
                    'method': 'POST',
                    'body': {'app_version': '1.0.0', 'shellui_version': '0.2.0'},
                },
            },
        )
        payload = response.json()['result']
        self.assertTrue(payload.get('isError'))

    @patch('apps.authapi.authentication.get_jwks_client')
    @override_settings(IDENTITY_SERVICE_URL='http://identity.test')
    @patch('apps.hosting.mcp_identity.requests.post')
    def test_approval_identity_failure_fail_closed(self, mock_post, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        mock_post.return_value.status_code = 404
        token = _agent_token(mcp_access='ask')
        response = self._rpc(
            'tools/call',
            {
                'name': 'hosting_v1_preview_create',
                'arguments': {
                    'path': '/hosting/v1/preview',
                    'method': 'POST',
                    'body': {'app_version': '1.0.0', 'shellui_version': '0.2.0'},
                },
            },
            token=token,
        )
        meta = response.json()['result'].get('meta') or {}
        self.assertEqual(meta.get('status'), 'pending')

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_ask_mode_requires_approval(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        token = _agent_token(mcp_access='ask')
        with patch('apps.hosting.mcp_views.create_approval_request', return_value={'id': 'abc'}):
            response = self._rpc(
                'tools/call',
                {
                    'name': 'hosting_v1_preview_create',
                    'arguments': {
                        'path': '/hosting/v1/preview',
                        'method': 'POST',
                        'body': {'app_version': '1.0.0', 'shellui_version': '0.2.0'},
                    },
                },
                token=token,
            )
        meta = response.json()['result'].get('meta') or {}
        self.assertEqual(meta.get('status'), 'pending')

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_deploy_token_list_never_returns_secrets(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        from apps.hosting.models import DeployToken
        from apps.hosting.deploy_tokens import hash_token, create_deploy_token

        create_deploy_token(company_id=42, name='ci', created_by_id=None)
        response = self._rpc(
            'tools/call',
            {
                'name': 'hosting_v1_deploy_tokens_retrieve',
                'arguments': {'path': '/hosting/v1/deploy-tokens', 'method': 'GET'},
            },
        )
        text = response.json()['result']['content'][0]['text']
        self.assertNotIn('"token"', text)
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            rows = parsed.get('result') or parsed
        else:
            rows = parsed
        if isinstance(rows, list):
            for row in rows:
                self.assertNotIn('token', row)
        self.assertNotIn(hash_token('shellui_dt_never'), text)
