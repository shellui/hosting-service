"""MCP tenant isolation: company A agents cannot reach company B hosting resources."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.hosting.deploy_tokens import create_deploy_token
from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, Deployment
from apps.hosting.tests.test_mcp import _agent_token


def _approve(company_id: int) -> None:
    CompanyHostingAccess.objects.update_or_create(
        company_id=company_id,
        defaults={'status': AccessStatus.APPROVED},
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
class McpTenantIsolationTests(TestCase):
    company_a = 10
    company_b = 20

    def setUp(self):
        self.client = Client()
        self.agent_id = str(uuid.uuid4())
        self.token = _agent_token(agent_id=self.agent_id, company_id=self.company_a, mcp_access='full')
        _approve(self.company_a)
        _approve(self.company_b)
        self.app_b = App.objects.create(
            name='tenant-b-site',
            slug='tenantbslug01',
            company_id=self.company_b,
            display_name='Tenant B',
            created_by_id=99,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.dep_b = Deployment.objects.create(
            app=self.app_b,
            app_version='1.0.0',
            shellui_version='0.2.0',
            deployed_by_id=99,
            storage_prefix='b/',
        )
        self.token_b, _raw = create_deploy_token(company_id=self.company_b, name='b-ci', created_by_id=99)

        self._revocation_ok = patch(
            'apps.hosting.mcp_revocation.fetch_revocation_payload',
            return_value={'revoked_agent_ids': [], 'agents': [], 'cache_seconds': 30},
        )
        self._revocation_ok.start()
        from apps.hosting import mcp_views

        mcp_views._server = None

    def tearDown(self):
        self._revocation_ok.stop()

    def _rpc_call(self, tool: str, arguments: dict):
        body = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'tools/call',
            'params': {'name': tool, 'arguments': arguments},
        }
        return self.client.post(
            reverse('mcp'),
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

    def _expect_forbidden_or_not_found(self, response) -> None:
        payload = response.json()
        if 'error' in payload:
            self.assertIn(payload['error'].get('code'), {-32602, -32601})
            return
        result = payload['result']
        if result.get('isError'):
            text = result['content'][0]['text']
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                body = {}
            code = body.get('statusCode') or body.get('status')
            if code is not None:
                self.assertIn(int(code), {403, 404})
                return
            self.assertTrue(result.get('isError'))
            return
        self.fail(f'expected 403/404 tool error, got: {payload}')

    def _assert_no_tenant_b_leak(self, text: str) -> None:
        forbidden = (
            self.app_b.slug,
            str(self.app_b.id),
            str(self.dep_b.id),
            str(self.token_b.id),
            'tenant-b-site',
            'Tenant B',
        )
        lowered = text.lower()
        for fragment in forbidden:
            self.assertNotIn(str(fragment).lower(), lowered)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_cross_tenant_app_by_slug_uuid_and_query(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        cases = [
            (
                'hosting_v1_apps_retrieve',
                {
                    'path': '/hosting/v1/apps/{app_ref}',
                    'method': 'GET',
                    'path_params': {'app_ref': self.app_b.slug},
                    'query': {'company_id': str(self.company_b)},
                },
            ),
            (
                'hosting_v1_apps_retrieve',
                {
                    'path': '/hosting/v1/apps/{app_ref}',
                    'method': 'GET',
                    'path_params': {'app_ref': str(self.app_b.id)},
                    'query': {'company_id': str(self.company_b)},
                },
            ),
            (
                'hosting_v1_apps_destroy',
                {
                    'path': '/hosting/v1/apps/{app_ref}',
                    'method': 'DELETE',
                    'path_params': {'app_ref': str(self.app_b.id)},
                    'query': {'company_id': str(self.company_b)},
                    'body': {'company_id': self.company_b},
                },
            ),
            (
                'hosting_v1_apps_deployments_list',
                {
                    'path': '/hosting/v1/apps/{app_ref}/deployments',
                    'method': 'GET',
                    'path_params': {'app_ref': self.app_b.slug},
                    'query': {'company_id': str(self.company_b)},
                },
            ),
            (
                'hosting_v1_apps_deployments_finalize_create',
                {
                    'path': '/hosting/v1/apps/{app_ref}/deployments/{deployment_id}/finalize',
                    'method': 'POST',
                    'path_params': {
                        'app_ref': self.app_b.slug,
                        'deployment_id': str(self.dep_b.id),
                    },
                    'query': {'company_id': str(self.company_b)},
                    'body': {'company_id': self.company_b},
                },
            ),
            (
                'hosting_v1_deploy_tokens_revoke_create',
                {
                    'path': '/hosting/v1/deploy-tokens/{token_id}/revoke',
                    'method': 'POST',
                    'path_params': {'token_id': str(self.token_b.id)},
                    'query': {'company_id': str(self.company_b)},
                },
            ),
        ]
        for tool, arguments in cases:
            with self.subTest(tool=tool, path=arguments.get('path')):
                response = self._rpc_call(tool, arguments)
                self.assertEqual(response.status_code, 200)
                self._expect_forbidden_or_not_found(response)
                self._assert_no_tenant_b_leak(response.content.decode())

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_actions_query_company_id_ignored_for_agents(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        response = self._rpc_call(
            'api_v1_actions_rules_list',
            {
                'path': '/api/v1/actions/rules',
                'method': 'GET',
                'query': {'company_id': str(self.company_b)},
            },
        )
        self.assertEqual(response.status_code, 200)
        text = response.json()['result']['content'][0]['text']
        self._assert_no_tenant_b_leak(text)
        parsed = json.loads(text)
        self.assertEqual(parsed.get('results'), [])

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_preview_create_never_attaches_to_other_company_slug(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        before = App.objects.filter(company_id=self.company_b, slug=self.app_b.slug).count()
        response = self._rpc_call(
            'hosting_v1_preview_create',
            {
                'path': '/hosting/v1/preview',
                'method': 'POST',
                'body': {
                    'slug': self.app_b.slug,
                    'company_id': self.company_b,
                    'app_version': '1.0.0',
                    'shellui_version': '0.2.0',
                },
                'query': {'company_id': str(self.company_b)},
            },
        )
        self.assertEqual(response.status_code, 200)
        self._expect_forbidden_or_not_found(response)
        after = App.objects.filter(company_id=self.company_b, slug=self.app_b.slug).count()
        self.assertEqual(before, after)
        self.assertEqual(App.objects.filter(company_id=self.company_a).count(), 0)
        self._assert_no_tenant_b_leak(response.content.decode())
