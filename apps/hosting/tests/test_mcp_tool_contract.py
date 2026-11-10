"""Contract tests for every Shellui MCP tool exposed by ``POST /mcp``.

Renaming a tool, dropping one, or changing its input schema (including required
fields, enums, and annotations) must fail. ``needs_approval`` is true when a
full-access agent still needs a human approval (destructive tools).
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import Resolver404, resolve, reverse
from drf_spectacular.generators import SchemaGenerator
from shellui_django.mcp.routing import materialize_openapi_path
from shellui_django.mcp.write_gate import decide_write

from apps.actions.registry import company_event_types, webhook_event_types
from apps.authapi.mcp_openapi import MCP_EXPLICIT_REGISTRY, MCP_GATEWAY_TOOL_NAMES
from apps.hosting.mcp_catalog import HIDDEN_MCP_ARGUMENT_NAMES, TRANSPORT_ARGUMENT_NAMES, published_mcp_tools
from apps.hosting.mcp_openapi_enums import DELIVERY_STATUS_VALUES
from apps.hosting.openapi_mcp_registry import MCP_SPECS
from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS
from apps.hosting.tests.test_mcp import _agent_token, _clear_revocation_cache

CONTRACT_PATH = Path(__file__).resolve().parent / 'fixtures' / 'mcp_tools_contract.json'

# Locked risk sets. Changing a flag requires editing this list in the same change.
READ_ONLY_TOOLS = frozenset(
    {
        'hosting_get_action_deliveries',
        'hosting_get_action_event_log',
        'hosting_get_action_event_log_retention',
        'hosting_get_action_rules',
        'hosting_get_apps',
        'hosting_get_apps_domains',
        'hosting_get_apps_environment',
        'hosting_get_deploy_tokens',
        'hosting_get_stats',
        'hosting_list_action_deliveries',
        'hosting_list_action_event_log',
        'hosting_list_action_event_log_types',
        'hosting_list_action_events',
        'hosting_list_action_rules',
        'hosting_list_apps',
        'hosting_list_apps_deployments',
        'hosting_list_apps_domains',
        'hosting_list_apps_environment',
        'hosting_list_apps_request_logs',
        'hosting_list_apps_runtime_logs',
    }
)
DESTRUCTIVE_TOOLS = frozenset(
    {
        'hosting_create_apps_deployments_finalize',
        'hosting_create_apps_deployments_rollback',
        'hosting_create_apps_domains',
        'hosting_create_apps_domains_refresh',
        'hosting_create_apps_environment',
        'hosting_delete_action_rules',
        'hosting_delete_apps',
        'hosting_delete_apps_domains',
        'hosting_delete_apps_environment',
        'hosting_replace_apps_environment',
        'hosting_requeue_action_deliveries',
        'hosting_revoke_deploy_token',
        'hosting_rotate_rule_secret',
        'hosting_send_test_rule',
    }
)
_TRANSPORT_PROPERTIES = TRANSPORT_ARGUMENT_NAMES | frozenset({'path_params', 'query', 'body'})
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')

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


def _sentence_count(text: str) -> int:
    parts = [part for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]
    return len(parts)


def build_mcp_tool_contract() -> dict:
    """Client-visible tools plus the access flags the server enforces."""
    schema = SchemaGenerator().get_schema(request=None, public=True)
    tools = published_mcp_tools(schema)
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
        required = list(tool['inputSchema'].get('required') or [])
        access[tool['name']] = {
            'read_only': bool(meta.get('read_only')),
            'destructive': bool(meta.get('destructive')),
            'readOnlyHint': tool['annotations']['readOnlyHint'],
            'destructiveHint': tool['annotations']['destructiveHint'],
            'needs_approval': bool(decision.needs_approval),
            'method': meta.get('method'),
            'path': meta.get('path'),
            'required': required,
            'path_params': list(meta.get('path_params') or []),
            'query_required': [name for name in (meta.get('query_required') or []) if name not in HIDDEN_MCP_ARGUMENT_NAMES],
            'body_required': [name for name in (meta.get('body_required') or []) if name not in HIDDEN_MCP_ARGUMENT_NAMES],
            'body_fields': [name for name in (meta.get('body_fields') or []) if name not in HIDDEN_MCP_ARGUMENT_NAMES],
            'query_fields': [name for name in (meta.get('query_fields') or []) if name not in HIDDEN_MCP_ARGUMENT_NAMES],
        }
        for name in meta.get('path_params') or []:
            assert name in required, tool['name']
            assert name in props, tool['name']
        for name in access[tool['name']]['body_required']:
            assert name in required, tool['name']
        for name in access[tool['name']]['query_required']:
            assert name in required, tool['name']
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
        self.assertEqual({tool['name'] for tool in listed}, set(MCP_GATEWAY_TOOL_NAMES.values()))
        live = build_mcp_tool_contract()
        self.assertEqual(live['tools'], pinned['tools'])
        self.assertEqual(live['access'], pinned['access'])
        for tool in listed:
            self.assertFalse(tool['name'].startswith('api_v1_'), tool['name'])
            self.assertTrue(tool['name'].startswith('hosting_'), tool['name'])
            self.assertNotIn('_v1_', tool['name'], tool['name'])
            self.assertEqual(tool['inputSchema']['additionalProperties'], False, tool['name'])
            self._assert_published_tool(tool)

    def _assert_published_tool(self, tool):
        name = tool['name']
        props = tool['inputSchema']['properties']
        required = list(tool['inputSchema'].get('required') or [])
        for forbidden in _TRANSPORT_PROPERTIES | HIDDEN_MCP_ARGUMENT_NAMES:
            self.assertNotIn(forbidden, props, name)
            self.assertNotIn(forbidden, required, name)
        self.assertEqual(tool['annotations']['readOnlyHint'], name in READ_ONLY_TOOLS, name)
        self.assertEqual(tool['annotations']['destructiveHint'], name in DESTRUCTIVE_TOOLS, name)
        self.assertFalse(tool['annotations']['readOnlyHint'] and tool['annotations']['destructiveHint'], name)
        description = tool['description']
        self.assertNotIn('—', description, name)
        self.assertNotIn('–', description, name)
        self.assertNotIn('...', description, name)
        count = _sentence_count(description)
        self.assertGreaterEqual(count, 1, description)
        self.assertLessEqual(count, 2, description)
        for prop_name, prop in props.items():
            self.assertTrue(str(prop.get('description') or '').strip(), f'{name}.{prop_name} needs a description')
            if 'enum' in prop:
                self.assertTrue(prop['enum'], f'{name}.{prop_name} enum is empty')
                self.assertNotIn(None, prop['enum'], name)

    def test_risk_annotations_match_locked_sets(self):
        contract = build_mcp_tool_contract()
        names = set(contract['access'])
        self.assertEqual(READ_ONLY_TOOLS | DESTRUCTIVE_TOOLS <= names, True)
        self.assertTrue(READ_ONLY_TOOLS.isdisjoint(DESTRUCTIVE_TOOLS))
        plain = names - READ_ONLY_TOOLS - DESTRUCTIVE_TOOLS
        self.assertEqual(READ_ONLY_TOOLS | DESTRUCTIVE_TOOLS | plain, names)
        for name, meta in contract['access'].items():
            self.assertEqual(meta['readOnlyHint'], meta['read_only'], name)
            self.assertEqual(meta['destructiveHint'], meta['destructive'], name)
            self.assertEqual(meta['read_only'], name in READ_ONLY_TOOLS, name)
            self.assertEqual(meta['destructive'], name in DESTRUCTIVE_TOOLS, name)
            if meta['needs_approval']:
                self.assertTrue(meta['destructive'], name)
                self.assertFalse(meta['read_only'], name)
            if meta['read_only']:
                self.assertFalse(meta['needs_approval'], name)
            operation_id = next(op for op, public in MCP_GATEWAY_TOOL_NAMES.items() if public == name)
            self.assertEqual(MCP_EXPLICIT_REGISTRY[operation_id]['destructive'], meta['destructive'], name)
            self.assertEqual(MCP_EXPLICIT_REGISTRY[operation_id]['read_only'], meta['read_only'], name)
            self.assertEqual(MCP_SPECS[operation_id].destructive, meta['destructive'], name)
            self.assertEqual(bool(meta['read_only']), MCP_SPECS[operation_id].side_effects.startswith('Read-only'), name)

    def test_enum_parameters_are_in_the_openapi_schema_and_the_tool(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        webhook_ids = [event.id for event in webhook_event_types()]
        company_ids = [event.id for event in company_event_types()]
        self.assertTrue(webhook_ids)
        self.assertTrue(company_ids)
        from apps.actions.registry import all_event_types

        staff_only = {event.id for event in all_event_types() if event.staff_only}
        expected = {
            'hosting_list_action_deliveries': {
                'status': list(DELIVERY_STATUS_VALUES),
                'event_type': webhook_ids,
            },
            'hosting_list_action_event_log': {'event_type': company_ids},
            'hosting_create_action_rules': {'event_type': webhook_ids},
            'hosting_update_action_rules': {'event_type': webhook_ids},
        }
        by_name = {tool['name']: tool for tool in build_mcp_tool_contract()['tools']}
        for tool_name, fields in expected.items():
            props = by_name[tool_name]['inputSchema']['properties']
            for field, values in fields.items():
                self.assertEqual(props[field]['enum'], values, f'{tool_name}.{field}')
                self.assertTrue(props[field]['description'], f'{tool_name}.{field}')
                self.assertTrue(set(values).isdisjoint(staff_only), f'{tool_name}.{field}')
        self._assert_openapi_enum(
            schema,
            'api_v1_actions_deliveries_list',
            'status',
            list(DELIVERY_STATUS_VALUES),
            where='query',
        )
        self._assert_openapi_enum(
            schema,
            'api_v1_actions_deliveries_list',
            'event_type',
            webhook_ids,
            where='query',
        )
        self._assert_openapi_enum(
            schema,
            'api_v1_actions_event_log_list',
            'event_type',
            company_ids,
            where='query',
        )
        self._assert_openapi_enum(
            schema,
            'api_v1_actions_rules_create',
            'event_type',
            webhook_ids,
            where='body',
        )
        self._assert_openapi_enum(
            schema,
            'api_v1_actions_rules_partial_update',
            'event_type',
            webhook_ids,
            where='body',
        )

    def _assert_openapi_enum(self, schema, operation_id, field, values, *, where):
        operation = None
        for path_item in schema['paths'].values():
            for op in path_item.values():
                if isinstance(op, dict) and op.get('operationId') == operation_id:
                    operation = op
        self.assertIsNotNone(operation, operation_id)
        if where == 'query':
            param = next(item for item in operation['parameters'] if item.get('name') == field)
            enum_schema = param['schema']
            self.assertTrue(param.get('description') or enum_schema.get('description'), field)
        else:
            enum_schema = self._body_property(schema, operation, field)
        self.assertEqual(enum_schema.get('enum'), values, f'{operation_id}.{field}')
        self.assertTrue(str(enum_schema.get('description') or '').strip(), f'{operation_id}.{field}')

    def _body_property(self, schema, operation, field):
        node = operation['requestBody']['content']['application/json']['schema']
        seen = set()
        while isinstance(node, dict) and '$ref' in node:
            ref = node['$ref']
            self.assertNotIn(ref, seen, ref)
            seen.add(ref)
            target = schema
            for part in ref.lstrip('#/').split('/'):
                target = target[part]
            node = target
        return node['properties'][field]

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_transport_arguments_do_not_retarget_the_tool(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        response = self.client.post(
            reverse('mcp'),
            data=json.dumps(
                {
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'tools/call',
                    'params': {
                        'name': 'hosting_list_apps',
                        'arguments': {'path': '/hosting/v1/stats', 'method': 'DELETE', 'url': 'https://example.test'},
                    },
                }
            ),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertNotIn('error', payload, payload)
        self.assertFalse(payload['result'].get('isError'), payload['result'])
        self.assertIsInstance(json.loads(payload['result']['content'][0]['text']), list)

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
