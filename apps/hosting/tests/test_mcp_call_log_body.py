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
                'outcome': 'allowed',
                'duration_ms': 12,
                'grant_version': 0,
            }
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body['tool'], 'hosting_v1_apps_list')
        self.assertEqual(body['resource_path'], '/hosting/v1/apps')
        self.assertNotIn('request_id', body)
        self.assertNotIn('mcp_jsonrpc_id', body)
        self.assertNotIn('error_code', body)
        self.assertNotIn('arguments', body)

    def test_success_omits_empty_error_code(self):
        body = build_identity_call_log_body(
            {
                'agent_id': 'a',
                'company_id': 0,
                'tool': 't',
                'operation_title': 'T',
                'resource_path': '/p',
                'http_method': 'GET',
                'access_kind': 'read',
                'outcome': 'allowed',
                'error_code': '',
                'http_status': 200,
            }
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertNotIn('error_code', body)

    def test_failed_includes_error_code(self):
        body = build_identity_call_log_body(
            {
                'agent_id': 'a',
                'company_id': 1,
                'tool': 't',
                'operation_title': 'T',
                'resource_path': '/p',
                'http_method': 'GET',
                'access_kind': 'read',
                'outcome': 'failed',
                'error_code': 'not_found',
                'http_status': 404,
            }
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body['error_code'], 'not_found')

    def test_pending_approval_requires_enum_error_code(self):
        body = build_identity_call_log_body(
            {
                'agent_id': 'a',
                'company_id': 1,
                'tool': 't',
                'operation_title': 'T',
                'resource_path': '/p',
                'http_method': 'POST',
                'access_kind': 'write',
                'outcome': 'pending_approval',
                'error_code': 'approval_pending',
                'http_status': 0,
            }
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body['error_code'], 'approval_pending')

    def test_rejects_allowed_with_error_code(self):
        self.assertIsNone(
            build_identity_call_log_body(
                {
                    'agent_id': 'a',
                    'company_id': 1,
                    'tool': 't',
                    'operation_title': 'T',
                    'resource_path': '/p',
                    'http_method': 'GET',
                    'access_kind': 'read',
                    'outcome': 'allowed',
                    'error_code': 'ok',
                    'http_status': 200,
                }
            )
        )

    def test_rejects_noncanonical_outcome(self):
        self.assertIsNone(
            build_identity_call_log_body(
                {
                    'agent_id': 'a',
                    'company_id': 1,
                    'tool': 't',
                    'operation_title': 'T',
                    'resource_path': '/p',
                    'http_method': 'GET',
                    'access_kind': 'read',
                    'outcome': 'success',
                    'http_status': 200,
                }
            )
        )

    def test_rejects_float_grant_version(self):
        self.assertIsNone(
            build_identity_call_log_body(
                {
                    'agent_id': 'a',
                    'company_id': 1,
                    'tool': 't',
                    'operation_title': 'T',
                    'resource_path': '/p',
                    'http_method': 'GET',
                    'access_kind': 'read',
                    'outcome': 'allowed',
                    'grant_version': 1.0,
                    'http_status': 200,
                }
            )
        )

    def test_rejects_incomplete(self):
        self.assertIsNone(build_identity_call_log_body({'agent_id': 'x'}))
