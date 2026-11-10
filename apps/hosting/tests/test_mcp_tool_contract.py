"""Contract tests for every Shellui MCP tool exposed by ``POST /mcp``.

Renaming a tool, dropping one, or changing its input schema (including required
fields) must fail. Access flags are pinned too: ``needs_approval`` is true when
a full-access agent still needs a human approval (destructive tools).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import Resolver404, resolve, reverse
from drf_spectacular.generators import SchemaGenerator
from shellui_django.mcp.openapi_tools import tools_from_schema
from shellui_django.mcp.routing import materialize_openapi_path
from shellui_django.mcp.write_gate import decide_write

from apps.authapi.mcp_openapi import MCP_REQUIRED_OPERATION_IDS
from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS
from apps.hosting.tests.test_mcp import _agent_token, _clear_revocation_cache

CONTRACT_PATH = Path(__file__).resolve().parent / 'fixtures' / 'mcp_tools_contract.json'

_PATH_SAMPLES = {
    'app_ref': 'auditapp',
    'deployment_id': '11111111-1111-1111-1111-111111111111',
    'domain_id': '22222222-2222-2222-2222-222222222222',
    'token_id': '33333333-3333-3333-3333-333333333333',
    'delivery_id': '44444444-4444-4444-4444-444444444444',
    'key': 'AUDIT_FLAG',
    'id': '1',
    'pk': '1',
}


def build_mcp_tool_contract() -> dict:
    """Client-visible tools plus the access flags the server enforces."""
    schema = SchemaGenerator().get_schema(request=None, public=True)
    tools = tools_from_schema(schema)
    client_tools = []
    access = {}
    for tool in tools:
        client_tools.append({key: value for key, value in tool.items() if not str(key).startswith('_')})
        meta = tool['_meta']
        decision = decide_write(
            method=str(meta.get('method') or 'GET'),
            access_mode='full',
            destructive=bool(meta.get('destructive')),
            allow_destructive_without_asking=False,
            tool_read_only=bool(meta.get('read_only')),
        )
        props = tool['inputSchema']['properties']
        access[tool['name']] = {
            'read_only': bool(meta.get('read_only')),
            'destructive': bool(meta.get('destructive')),
            'needs_approval': bool(decision.needs_approval),
            'method': meta.get('method'),
            'path': meta.get('path'),
            'required': list(tool['inputSchema'].get('required') or []),
            'path_params': list(meta.get('path_params') or []),
            'query_required': list(meta.get('query_required') or []),
            'body_required': list(meta.get('body_required') or []),
            'body_fields': list(meta.get('body_fields') or []),
            'query_fields': list(meta.get('query_fields') or []),
        }
        # Required path/method are part of every tool. Path params are required when the template has them.
        if meta.get('path_params'):
            assert 'path_params' in tool['inputSchema']['required'], tool['name']
            assert props['path_params']['required'] == list(meta['path_params']), tool['name']
        if meta.get('body_required'):
            assert props['body']['required'] == list(meta['body_required']), tool['name']
        if meta.get('query_required'):
            assert props['query']['required'] == list(meta['query_required']), tool['name']
    return {'tools': client_tools, 'access': access}


@override_settings(
    **MCP_SIGNING_TEST_SETTINGS,
    DEBUG=True,
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_AUDIENCE='',
    IDENTITY_ISSUER='',
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    HOSTING_MCP_RESOURCE='http://127.0.0.1/mcp',
    HOSTING_BACKEND='filesystem',
    IDENTITY_SERVICE_URL='',
)
class McpToolContractTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.agent_id = str(uuid.uuid4())
        self.token = _agent_token(agent_id=self.agent_id, company_id=42, mcp_access='read_only')
        _clear_revocation_cache(42)
        self._revocation_ok = patch(
            'apps.hosting.mcp_revocation.fetch_revocation_payload',
            return_value={'revoked_agent_ids': []},
        )
        self._revocation_ok.start()
        self._delegated_live = patch(
            'apps.hosting.mcp_server.delegated_live_authority_state',
            return_value=('ok', True),
        )
        self._delegated_live.start()
        from apps.hosting import mcp_views

        mcp_views._server = None

    def tearDown(self):
        self._delegated_live.stop()
        self._revocation_ok.stop()

    def _rpc(self, method: str):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': {}}
        return self.client.post(
            reverse('mcp'),
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_tools_list_matches_pinned_contract(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        self.assertTrue(CONTRACT_PATH.is_file(), f'missing contract snapshot {CONTRACT_PATH}')
        pinned = json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))
        response = self._rpc('tools/list')
        self.assertEqual(response.status_code, 200, response.content)
        listed = response.json()['result']['tools']
        self.assertEqual(listed, pinned['tools'])
        self.assertEqual([tool['name'] for tool in listed], sorted(tool['name'] for tool in listed))
        self.assertEqual({tool['name'] for tool in listed}, set(MCP_REQUIRED_OPERATION_IDS))
        live = build_mcp_tool_contract()
        self.assertEqual(live['tools'], pinned['tools'])
        self.assertEqual(live['access'], pinned['access'])
        for tool in listed:
            required = tool['inputSchema']['required']
            self.assertIn('path', required, tool['name'])
            self.assertIn('method', required, tool['name'])
            self.assertEqual(tool['inputSchema']['additionalProperties'], False, tool['name'])

    def test_every_tool_path_resolves_to_a_view(self):
        contract = build_mcp_tool_contract()
        for name, meta in contract['access'].items():
            params = {}
            for param in meta['path_params']:
                if param not in _PATH_SAMPLES:
                    self.fail(f'{name} has path parameter {param!r} with no resolver sample')
                params[param] = _PATH_SAMPLES[param]
            path = materialize_openapi_path(meta['path'], params)
            try:
                match = resolve(path)
            except Resolver404 as exc:
                self.fail(f'{name} schema path {meta["path"]} materialized to {path} and did not resolve: {exc}')
            self.assertIsNotNone(match.func, name)
            self.assertEqual(meta['method'], meta['method'].upper(), name)
            if meta['needs_approval']:
                self.assertTrue(meta['destructive'], name)
                self.assertFalse(meta['read_only'], name)
            if meta['read_only']:
                self.assertFalse(meta['needs_approval'], name)
