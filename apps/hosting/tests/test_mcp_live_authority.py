"""Live delegated authority check (Identity POST mcp-delegated-agent-authority)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.hosting.mcp_live_authority import bump_delegated_authority_cache_on_identity_failure, delegated_live_authority_ok
from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS

_GID = "01234567-89ab-cdef-0123-456789abcdef"


def _delegated_claims(**kwargs):
    base = {
        "agent_id": "agent-delegated",
        "company_id": 42,
        "mcp_authority": "delegated",
        "global_company_id": _GID,
        "grant_version": 1,
        "company_binding_version": 0,
    }
    base.update(kwargs)
    return base


@override_settings(
    **MCP_SIGNING_TEST_SETTINGS,
    IDENTITY_SERVICE_URL="http://identity.test",
    IDENTITY_ISSUER="http://identity.test",
)
class DelegatedLiveAuthorityTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_personal_regional_skips_http(self, _assert):
        self.assertTrue(
            delegated_live_authority_ok({"agent_id": "a", "company_id": 42, "grant_version": 0})
        )

    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_delegated_without_global_skips_http(self, _assert):
        self.assertTrue(
            delegated_live_authority_ok(
                {"agent_id": "a", "company_id": 42, "mcp_authority": "delegated", "grant_version": 0}
            )
        )

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_delegated_ok_matching_triplet(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "authorized": True,
            "revoked": False,
            "paused": False,
            "agent_id": "agent-delegated",
            "company_id": 42,
            "global_company_id": _GID,
            "grant_version": 1,
            "company_binding_version": 0,
        }
        mock_post.return_value = mock_resp
        self.assertTrue(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_delegated_triplet_zero_versions_valid(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "authorized": True,
            "revoked": False,
            "paused": False,
            "agent_id": "agent-delegated",
            "company_id": 42,
            "global_company_id": _GID,
            "grant_version": 0,
            "company_binding_version": 0,
        }
        mock_post.return_value = mock_resp
        claims = _delegated_claims(grant_version=0, company_binding_version=0)
        self.assertTrue(delegated_live_authority_ok(claims))
        body = mock_post.call_args.kwargs.get("json") or {}
        self.assertEqual(body["grant_version"], 0)
        self.assertEqual(body["company_binding_version"], 0)

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_delegated_rejects_string_grant_in_response(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "authorized": True,
            "revoked": False,
            "paused": False,
            "agent_id": "agent-delegated",
            "company_id": 42,
            "global_company_id": _GID,
            "grant_version": "1",
            "company_binding_version": 0,
        }
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_delegated_requires_authorized_revoked_paused_shape(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "authorized": True,
            "revoked": True,
            "paused": False,
            "agent_id": "agent-delegated",
            "company_id": 42,
            "global_company_id": _GID,
            "grant_version": 1,
            "company_binding_version": 0,
        }
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_delegated_network_failure(self, _assert, mock_post):
        mock_post.side_effect = OSError("network")
        self.assertFalse(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_cache_short_circuits_second_call(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "authorized": True,
            "revoked": False,
            "paused": False,
            "agent_id": "agent-delegated",
            "company_id": 42,
            "global_company_id": _GID,
            "grant_version": 1,
            "company_binding_version": 0,
        }
        mock_post.return_value = mock_resp
        claims = _delegated_claims()
        self.assertTrue(delegated_live_authority_ok(claims))
        self.assertTrue(delegated_live_authority_ok(claims))
        self.assertEqual(mock_post.call_count, 1)

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_revocation_assertion", return_value="assertion")
    def test_bump_generation_invalidates_positive_cache(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "authorized": True,
            "revoked": False,
            "paused": False,
            "agent_id": "agent-delegated",
            "company_id": 42,
            "global_company_id": _GID,
            "grant_version": 1,
            "company_binding_version": 0,
        }
        mock_post.return_value = mock_resp
        claims = _delegated_claims()
        self.assertTrue(delegated_live_authority_ok(claims))
        bump_delegated_authority_cache_on_identity_failure()
        self.assertTrue(delegated_live_authority_ok(claims))
        self.assertEqual(mock_post.call_count, 2)
