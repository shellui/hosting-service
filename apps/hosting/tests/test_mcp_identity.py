"""Unit tests for MCP identity forwarding (approval consume and assertions)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import jwt
from django.test import SimpleTestCase, override_settings

from apps.hosting import mcp_identity
from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS


@override_settings(
    **MCP_SIGNING_TEST_SETTINGS,
    IDENTITY_SERVICE_URL="http://identity.test",
)
class McpIdentityConsumeTests(SimpleTestCase):
    def setUp(self):
        mcp_identity._APPROVAL_ROUTE_CONTEXT.clear()

    def tearDown(self):
        mcp_identity._APPROVAL_ROUTE_CONTEXT.clear()

    def _payload(self) -> dict:
        return {
            "agent_id": "agent-1",
            "company_id": 42,
            "service": "hosting",
            "action": "hosting_v1_preview_create",
            "arguments_hash": "abc",
        }

    @patch(
        "apps.hosting.mcp_identity.current_mcp_agent_claims",
        return_value={"company_id": 42, "grant_version": 0},
    )
    @patch("apps.hosting.mcp_identity.requests.post")
    def test_consume_requires_consumed_true_on_200(self, mock_post, _claims):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"consumed": False}
        mock_post.return_value = mock_resp
        mcp_identity._APPROVAL_ROUTE_CONTEXT["ap1"] = self._payload()
        self.assertFalse(mcp_identity.consume_approval("ap1"))

    @patch(
        "apps.hosting.mcp_identity.current_mcp_agent_claims",
        return_value={"company_id": 42, "grant_version": 0},
    )
    @patch("apps.hosting.mcp_identity.requests.post")
    def test_consume_rejects_2xx_without_consumed_true(self, mock_post, _claims):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_resp
        mcp_identity._APPROVAL_ROUTE_CONTEXT["ap1"] = self._payload()
        self.assertFalse(mcp_identity.consume_approval("ap1"))

    @patch(
        "apps.hosting.mcp_identity.current_mcp_agent_claims",
        return_value={"company_id": 42, "grant_version": 0},
    )
    @patch("apps.hosting.mcp_identity.requests.post")
    def test_consume_accepts_literal_true(self, mock_post, _claims):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"consumed": True}
        mock_post.return_value = mock_resp
        mcp_identity._APPROVAL_ROUTE_CONTEXT["ap1"] = self._payload()
        self.assertTrue(mcp_identity.consume_approval("ap1"))


@override_settings(
    **MCP_SIGNING_TEST_SETTINGS,
    IDENTITY_SERVICE_URL="http://identity.test",
)
class McpIdentityApprovalAssertionTests(SimpleTestCase):
    @patch(
        "apps.hosting.mcp_identity.current_mcp_agent_claims",
        return_value={"company_id": 1, "grant_version": 3},
    )
    def test_approval_route_assertion_includes_grant_version_when_set(self, _claims):
        t = mcp_identity._approval_route_assertion(
            {
                "agent_id": "a",
                "company_id": 1,
                "service": "hosting",
                "action": "t",
                "arguments_hash": "h",
            }
        )
        self.assertIsInstance(t, str)
        self.assertGreater(len(t), 20)

    @patch(
        "apps.hosting.mcp_identity.current_mcp_agent_claims",
        return_value={"company_id": 1},
    )
    def test_personal_agent_without_grant_omits_grant_claim(self, _claims):
        t = mcp_identity._approval_route_assertion(
            {
                "agent_id": "a",
                "company_id": 1,
                "service": "hosting",
                "action": "t",
                "arguments_hash": "h",
            }
        )
        self.assertIsInstance(t, str)

    @patch(
        "apps.hosting.mcp_identity.current_mcp_agent_claims",
        return_value={
            "company_id": 1,
            "mcp_authority": "delegated",
            "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
            "grant_version": 2,
            "company_binding_version": 1,
        },
    )
    def test_delegated_assertion_includes_global_triplet(self, _claims):
        t = mcp_identity._approval_route_assertion(
            {
                "agent_id": "a",
                "company_id": 1,
                "service": "hosting",
                "action": "t",
                "arguments_hash": "h",
            }
        )
        self.assertIsInstance(t, str)
        payload = jwt.decode(t, options={"verify_signature": False})
        self.assertEqual(
            payload["global_company_id"], "01234567-89ab-cdef-0123-456789abcdef"
        )
        self.assertEqual(payload["grant_version"], 2)
        self.assertEqual(payload["company_binding_version"], 1)
