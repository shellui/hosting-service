"""Agent JWT rejection for delegated authority hints."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.authapi.mcp_authority import authority_context_for_call_log
from apps.authapi.principal import principal_from_claims


class AgentPrincipalAuthorityTests(SimpleTestCase):
    def test_rejects_global_delegated_profile(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    "sub": "agent:x",
                    "agent_id": "x",
                    "company_id": 1,
                    "grant_version": 0,
                    "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
                    "mcp_authority": "global_delegated",
                }
            )
        self.assertIn(
            "mcp_authority_global_delegated_on_direct_resource", str(ctx.exception)
        )

    def test_rejects_global_uuid_without_delegated_marker(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    "sub": "agent:x",
                    "agent_id": "x",
                    "company_id": 1,
                    "grant_version": 0,
                    "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
                }
            )
        self.assertIn("mcp_authority_delegated_on_direct_resource", str(ctx.exception))

    def test_accepts_regional_delegated_triplet(self):
        p = principal_from_claims(
            {
                "sub": "agent:x",
                "agent_id": "x",
                "company_id": 1,
                "mcp_authority": "delegated",
                "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
                "global_agent_id": "fedcba98-7654-3210-fedc-ba9876543210",
                "grant_version": 0,
                "company_binding_version": 0,
            }
        )
        self.assertEqual(p.agent_id, "x")
        self.assertEqual(p.company_id, 1)

    def test_rejects_delegated_triplet_without_global_agent_id(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    "sub": "agent:x",
                    "agent_id": "x",
                    "company_id": 1,
                    "mcp_authority": "delegated",
                    "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
                    "grant_version": 0,
                    "company_binding_version": 0,
                }
            )
        self.assertIn("mcp_authority_global_agent_id_invalid", str(ctx.exception))

    def test_rejects_delegated_incomplete_triplet(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    "sub": "agent:x",
                    "agent_id": "x",
                    "company_id": 1,
                    "mcp_authority": "delegated",
                    "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
                    "grant_version": 1,
                }
            )
        self.assertIn("mcp_authority_delegated_triplet_incomplete", str(ctx.exception))

    def test_rejects_invalid_grant_version_string(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    "sub": "agent:x",
                    "agent_id": "x",
                    "company_id": 1,
                    "grant_version": "not-a-digit",
                }
            )
        self.assertIn("mcp_authority_grant_version_invalid", str(ctx.exception))

    def test_rejects_float_company_id(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    "sub": "agent:x",
                    "agent_id": "x",
                    "company_id": 42.0,
                    "grant_version": 0,
                }
            )
        self.assertIn("company_id", str(ctx.exception))

    def test_rejects_personal_agent_missing_grant_version(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    "sub": "agent:x",
                    "agent_id": "x",
                    "company_id": 1,
                }
            )
        self.assertIn("mcp_authority_grant_version_required", str(ctx.exception))


class AuthorityContextForCallLogTests(SimpleTestCase):
    def test_personal_includes_grant_only(self):
        self.assertEqual(
            authority_context_for_call_log({"grant_version": 0}),
            {"grant_version": 0},
        )

    def test_delegated_includes_global_binding_triplet(self):
        ctx = authority_context_for_call_log(
            {
                "mcp_authority": "delegated",
                "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
                "grant_version": 1,
                "company_binding_version": 2,
            }
        )
        self.assertEqual(ctx["grant_version"], 1)
        self.assertEqual(ctx["company_binding_version"], 2)
        self.assertEqual(
            ctx["global_company_id"], "01234567-89ab-cdef-0123-456789abcdef"
        )

    def test_incomplete_binding_pair_omits_global_and_binding(self):
        """Send neither field unless both ``global_company_id`` and ``company_binding_version`` parse."""
        self.assertEqual(
            authority_context_for_call_log(
                {
                    "grant_version": 0,
                    "global_company_id": "01234567-89ab-cdef-0123-456789abcdef",
                }
            ),
            {"grant_version": 0},
        )
        self.assertEqual(
            authority_context_for_call_log({"grant_version": 0, "company_binding_version": 1}),
            {"grant_version": 0},
        )
