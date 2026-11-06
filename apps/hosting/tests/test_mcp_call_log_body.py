"""Identity MCP call log body allowlist."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.hosting.mcp_call_log_body import build_identity_call_log_body


class CallLogBodyTests(SimpleTestCase):
    def test_builds_allowlisted_fields(self):
        body = build_identity_call_log_body(
            {
                'agent_id': 'a1',
                'company_id': 42,
                'service': 'hosting',
                'tool': 'hosting_v1_apps_list',
                'operation_title': 'List apps',
                'resource_path': '/hosting/v1/apps',
                'http_method': 'GET',
                'http_status': 200,
                'access_kind': 'read',
                'outcome': 'success',
                'error_code': 'ok',
                'duration_ms': 12,
                'request_id': 'r1',
                'mcp_jsonrpc_id': 7,
            }
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body['tool'], 'hosting_v1_apps_list')
        self.assertEqual(body['resource_path'], '/hosting/v1/apps')
        self.assertEqual(body['request_id'], 'r1')
        self.assertNotIn('arguments', body)

    def test_rejects_incomplete(self):
        self.assertIsNone(build_identity_call_log_body({'agent_id': 'x'}))
