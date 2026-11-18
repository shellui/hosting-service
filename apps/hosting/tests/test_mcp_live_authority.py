"""Live delegated authority check (Identity ``POST .../mcp-agent-delegated-authority``)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.hosting.mcp_live_authority import (
    DELEGATED_AUTH_REASON_DENY,
    DELEGATED_AUTH_REASON_UNAVAILABLE,
    bump_delegated_authority_cache_on_identity_failure,
    delegated_live_authority_ok,
    delegated_live_authority_state,
)
from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS

_GID = "01234567-89ab-cdef-0123-456789abcdef"
_GAID = "fedcba98-7654-3210-fedc-ba9876543210"


def _ok_identity_body(*, agent_id: str, company_id: int = 42) -> dict:
    """Fixed 15 keys from Identity ``_delegated_authority_fixed_payload`` (PR #135 head)."""
    return {
        "authorized": True,
        "active": True,
        "revoked": False,
        "paused": False,
        "agent_id": agent_id,
        "company_id": company_id,
        "global_agent_id": _GAID,
        "global_company_id": _GID,
        "grant_version": 1,
        "company_binding_version": 0,
        "access_mode": "full",
        "read_level": "safe",
        "allow_destructive": False,
        "services_allowed": ["hosting", "storage"],
        "revoked_at": None,
    }


def _delegated_claims(**kwargs):
    base = {
        "agent_id": "aabbccdd-eeff-0011-aabb-ccddeeff0011",
        "company_id": 42,
        "mcp_authority": "delegated",
        "global_company_id": _GID,
        "global_agent_id": _GAID,
        "grant_version": 1,
        "company_binding_version": 0,
        "mcp_access": "full",
        "mcp_read": "safe",
        "mcp_destructive": False,
        "scope": "hosting storage",
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

    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_personal_regional_skips_http(self, _assert):
        self.assertTrue(
            delegated_live_authority_ok({"agent_id": "a", "company_id": 42, "grant_version": 0})
        )

    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_delegated_without_global_skips_http(self, _assert):
        self.assertTrue(
            delegated_live_authority_ok(
                {"agent_id": "a", "company_id": 42, "mcp_authority": "delegated", "grant_version": 0}
            )
        )

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_delegated_ok_matching_triplet(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _ok_identity_body(agent_id=aid)
        mock_post.return_value = mock_resp
        self.assertTrue(delegated_live_authority_ok(_delegated_claims(agent_id=aid)))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_delegated_triplet_zero_versions_valid(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        body = _ok_identity_body(agent_id=aid)
        body["grant_version"] = 0
        body["company_binding_version"] = 0
        mock_resp.json.return_value = body
        mock_post.return_value = mock_resp
        claims = _delegated_claims(agent_id=aid, grant_version=0, company_binding_version=0)
        self.assertTrue(delegated_live_authority_ok(claims))
        posted = mock_post.call_args.kwargs.get("json") or {}
        self.assertEqual(posted["grant_version"], 0)
        self.assertEqual(posted["company_binding_version"], 0)

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_delegated_rejects_string_grant_in_response(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        body = _ok_identity_body(agent_id=_delegated_claims()["agent_id"])
        body["grant_version"] = "1"
        mock_resp.json.return_value = body
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_delegated_requires_authorized_revoked_paused_shape(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        body = _ok_identity_body(agent_id=_delegated_claims()["agent_id"])
        body["revoked"] = True
        mock_resp.json.return_value = body
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_delegated_network_failure(self, _assert, mock_post):
        mock_post.side_effect = OSError("network")
        reason, allowed = delegated_live_authority_state(_delegated_claims())
        self.assertFalse(allowed)
        self.assertEqual(reason, DELEGATED_AUTH_REASON_UNAVAILABLE)

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_cache_short_circuits_second_call(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _ok_identity_body(agent_id=aid)
        mock_post.return_value = mock_resp
        claims = _delegated_claims(agent_id=aid)
        self.assertTrue(delegated_live_authority_ok(claims))
        self.assertTrue(delegated_live_authority_ok(claims))
        self.assertEqual(mock_post.call_count, 1)

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_bump_generation_invalidates_positive_cache(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _ok_identity_body(agent_id=aid)
        mock_post.return_value = mock_resp
        claims = _delegated_claims(agent_id=aid)
        self.assertTrue(delegated_live_authority_ok(claims))
        bump_delegated_authority_cache_on_identity_failure()
        self.assertTrue(delegated_live_authority_ok(claims))
        self.assertEqual(mock_post.call_count, 2)

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_404_agent_missing_denies(self, _assert, mock_post):
        mock_post.return_value = MagicMock(status_code=404, json=MagicMock(side_effect=ValueError))
        self.assertFalse(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_404_json_error_body_denies_not_unavailable(self, _assert, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"error": "not_found", "detail": "unknown"}
        mock_post.return_value = mock_resp
        reason, allowed = delegated_live_authority_state(_delegated_claims())
        self.assertFalse(allowed)
        self.assertEqual(reason, DELEGATED_AUTH_REASON_DENY)

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_403_stale_binding_denies(self, _assert, mock_post):
        mock_post.return_value = MagicMock(status_code=403, json=lambda: {"authorized": False})
        self.assertFalse(delegated_live_authority_ok(_delegated_claims()))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_token_without_hosting_scope_denies(self, _assert, mock_post):
        """JWT ``scope`` must be a subset of Identity ``services_allowed`` (must include ``hosting`` here)."""
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _ok_identity_body(agent_id=aid)
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims(agent_id=aid, scope="storage")))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_services_allowed_must_cover_jwt_scope(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        body = _ok_identity_body(agent_id=aid)
        body["services_allowed"] = ["hosting"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims(agent_id=aid, scope="hosting storage")))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_access_mode_read_level_must_match_token(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        body = _ok_identity_body(agent_id=aid)
        body["access_mode"] = "read_only"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims(agent_id=aid)))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_revoked_at_optional_on_live_payload(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        body = _ok_identity_body(agent_id=aid)
        body["revoked_at"] = 1700000000
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_post.return_value = mock_resp
        self.assertTrue(delegated_live_authority_ok(_delegated_claims(agent_id=aid)))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_extra_top_level_field_in_200_denies(self, _assert, mock_post):
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        body = _ok_identity_body(agent_id=aid)
        body["unexpected"] = True
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(_delegated_claims(agent_id=aid)))

    @patch("apps.hosting.mcp_live_authority.requests.post")
    @patch("apps.hosting.mcp_live_authority.build_mcp_delegated_agent_authority_assertion", return_value="assertion")
    def test_binding_mismatch_200_denies(self, _assert, mock_post):
        """Binding triple mismatch: same 15 keys as live; ``authorized`` false."""
        aid = "aabbccdd-eeff-0011-aabb-ccddeeff0011"
        claims = _delegated_claims(agent_id=aid)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "authorized": False,
            "active": False,
            "revoked": False,
            "paused": False,
            "agent_id": aid,
            "company_id": 42,
            "global_agent_id": _GAID,
            "global_company_id": _GID,
            "grant_version": 1,
            "company_binding_version": 0,
            "access_mode": "full",
            "read_level": "safe",
            "allow_destructive": False,
            "services_allowed": ["hosting", "storage"],
            "revoked_at": None,
        }
        mock_post.return_value = mock_resp
        self.assertFalse(delegated_live_authority_ok(claims))
