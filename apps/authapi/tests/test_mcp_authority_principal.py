"""Agent JWT rejection for delegated authority hints."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.authapi.principal import principal_from_claims


class AgentPrincipalAuthorityTests(SimpleTestCase):
    def test_rejects_canonical_global_company_id(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    'sub': 'agent:x',
                    'agent_id': 'x',
                    'company_id': 1,
                    'global_company_id': '01234567-89ab-cdef-0123-456789abcdef',
                }
            )
        self.assertIn('Globally delegated', str(ctx.exception))

    def test_rejects_invalid_grant_version_string(self):
        with self.assertRaises(ValueError) as ctx:
            principal_from_claims(
                {
                    'sub': 'agent:x',
                    'agent_id': 'x',
                    'company_id': 1,
                    'grant_version': 'not-a-digit',
                }
            )
        self.assertIn('grant_version', str(ctx.exception))
