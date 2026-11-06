"""Identity MCP call log body allowlist."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.hosting.mcp_call_log_body import build_identity_call_log_body


def _base(**kwargs):
    d = {
        'agent_id': 'a1',
        'company_id': 42,
        'service': 'hosting',
        'tool': 'hosting_v1_apps_list',
        'path': '/mcp',
        'method': 'POST',
        'status': 200,
        'access_kind': 'read',
        'outcome': 'allowed',
        'duration_ms': 12,
        'grant_version': 0,
    }
    d.update(kwargs)
    return d


class CallLogBodyTests(SimpleTestCase):
    def test_builds_allowlisted_fields(self):
        body = build_identity_call_log_body(_base())
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body['tool'], 'hosting_v1_apps_list')
        self.assertEqual(body['path'], '/mcp')
        self.assertEqual(body['method'], 'POST')
        self.assertNotIn('operation_title', body)
        self.assertNotIn('request_id', body)
        self.assertNotIn('mcp_jsonrpc_id', body)
        self.assertNotIn('error_code', body)
        self.assertNotIn('arguments', body)

    def test_success_omits_empty_error_code(self):
        body = build_identity_call_log_body(
            _base(
                agent_id='a',
                company_id=0,
                tool='t',
                outcome='allowed',
                error_code='',
            )
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertNotIn('error_code', body)

    def test_failed_includes_error_code(self):
        body = build_identity_call_log_body(
            _base(
                agent_id='a',
                company_id=1,
                tool='t',
                outcome='failed',
                error_code='not_found',
                status=404,
            )
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body['error_code'], 'not_found')

    def test_pending_approval_requires_enum_error_code(self):
        body = build_identity_call_log_body(
            _base(
                agent_id='a',
                company_id=1,
                tool='t',
                access_kind='write',
                outcome='pending_approval',
                error_code='approval_pending',
                status=0,
            )
        )
        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(body['error_code'], 'approval_pending')

    def test_rejects_allowed_with_error_code(self):
        self.assertIsNone(
            build_identity_call_log_body(
                _base(
                    agent_id='a',
                    company_id=1,
                    tool='t',
                    access_kind='read',
                    outcome='allowed',
                    error_code='ok',
                    status=200,
                )
            )
        )

    def test_rejects_noncanonical_outcome(self):
        self.assertIsNone(
            build_identity_call_log_body(
                _base(
                    agent_id='a',
                    company_id=1,
                    tool='t',
                    access_kind='read',
                    outcome='success',
                    status=200,
                )
            )
        )

    def test_rejects_float_grant_version(self):
        self.assertIsNone(
            build_identity_call_log_body(
                _base(
                    agent_id='a',
                    company_id=1,
                    tool='t',
                    access_kind='read',
                    outcome='allowed',
                    grant_version=1.0,
                    status=200,
                )
            )
        )

    def test_rejects_openapi_path_instead_of_mcp(self):
        """Identity ``fixed_resource_label_for_service`` only accepts POST ``/mcp``."""
        self.assertIsNone(
            build_identity_call_log_body(
                {
                    'agent_id': 'a',
                    'company_id': 1,
                    'service': 'hosting',
                    'tool': 't',
                    'path': '/hosting/v1/apps',
                    'method': 'GET',
                    'status': 200,
                    'access_kind': 'read',
                    'outcome': 'allowed',
                    'duration_ms': 0,
                }
            )
        )

    def test_rejects_get_mcp(self):
        self.assertIsNone(
            build_identity_call_log_body(
                _base(method='GET', path='/mcp', outcome='allowed', status=200)
            )
        )

    def test_incomplete(self):
        self.assertIsNone(build_identity_call_log_body({'agent_id': 'x'}))
