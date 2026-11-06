"""Unit tests for MCP identity forwarding (approval consume and assertions)."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS
from apps.hosting import mcp_identity


@override_settings(
    **MCP_SIGNING_TEST_SETTINGS,
    IDENTITY_SERVICE_URL='http://identity.test',
)
class McpIdentityConsumeTests(SimpleTestCase):
    def setUp(self):
        mcp_identity._APPROVAL_ROUTE_CONTEXT.clear()

    def tearDown(self):
        mcp_identity._APPROVAL_ROUTE_CONTEXT.clear()

    def _payload(self) -> dict:
        return {
            'agent_id': 'agent-1',
            'company_id': 42,
            'service': 'hosting',
            'action': 'hosting_v1_preview_create',
            'arguments_hash': 'abc',
        }

    @patch('apps.hosting.mcp_identity.requests.post')
    def test_consume_requires_consumed_true_on_200(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'consumed': False}
        mock_post.return_value = mock_resp
        mcp_identity._APPROVAL_ROUTE_CONTEXT['ap1'] = self._payload()
        self.assertFalse(mcp_identity.consume_approval('ap1'))

    @patch('apps.hosting.mcp_identity.requests.post')
    def test_consume_rejects_2xx_without_consumed_true(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {'status': 'ok'}
        mock_post.return_value = mock_resp
        mcp_identity._APPROVAL_ROUTE_CONTEXT['ap1'] = self._payload()
        self.assertFalse(mcp_identity.consume_approval('ap1'))

    @patch('apps.hosting.mcp_identity.requests.post')
    def test_consume_accepts_literal_true(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'consumed': True}
        mock_post.return_value = mock_resp
        mcp_identity._APPROVAL_ROUTE_CONTEXT['ap1'] = self._payload()
        self.assertTrue(mcp_identity.consume_approval('ap1'))


@override_settings(
    **MCP_SIGNING_TEST_SETTINGS,
    IDENTITY_SERVICE_URL='http://identity.test',
)
class McpIdentityApprovalAssertionTests(SimpleTestCase):
    def test_build_mcp_approval_assertion_accepts_optional_identity_claim_fields(self):
        """When django-commons adds optional typed claims, forward them from the agent JWT."""
        from shellui_django.mcp.internal import build_mcp_approval_assertion

        params = inspect.signature(build_mcp_approval_assertion).parameters
        if 'global_company_id' not in params:
            self.skipTest('shellui-django build_mcp_approval_assertion has no global_company_id yet')
        gid = '01234567-89ab-cdef-0123-456789abcdef'
        with patch('apps.hosting.mcp_identity.current_mcp_agent_claims', return_value={'global_company_id': gid, 'grant_version': 0}):
            assertion = mcp_identity._approval_route_assertion(
                {
                    'agent_id': 'a',
                    'company_id': 1,
                    'service': 'hosting',
                    'action': 't',
                    'arguments_hash': 'h',
                }
            )
        self.assertIsInstance(assertion, str)
        self.assertTrue(len(assertion) > 20)
