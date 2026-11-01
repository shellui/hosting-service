"""Shellui MCP endpoint and OpenAPI exposure."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import jwt
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.hosting.mcp_revocation import _CACHE_KEY


def _agent_token(
    *,
    secret: str = 'test-secret',
    agent_id: str | None = None,
    company_id: int = 42,
    mcp_access: str = 'read_only',
    mcp_destructive: bool = False,
    scope: str = 'hosting',
    aud: str | list[str] = 'shellui-mcp',
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
)
class McpEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.agent_id = str(uuid.uuid4())
        self.token = _agent_token(agent_id=self.agent_id)

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
        token = _agent_token(aud='http://testserver/mcp')
        response = self._rpc('tools/list', token=token)
        self.assertEqual(response.status_code, 200)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_revoked_agent_refused(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        from django.core.cache import cache

        cache.set(_CACHE_KEY, [self.agent_id], timeout=60)
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
