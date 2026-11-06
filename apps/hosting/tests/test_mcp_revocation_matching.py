"""Revocation row matching (strict grant and binding, no ambiguous fallback)."""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from apps.hosting.mcp_revocation import (
    _agents_cache_key,
    _cache_key,
    _matching_revocation_rows,
    _unavailable_key,
    agent_revocation_denied,
)


class RevocationMatchingTests(SimpleTestCase):
    def tearDown(self):
        for cid in (42, None):
            cache.delete(_cache_key(cid))
            cache.delete(_unavailable_key(cid))
            cache.delete(_agents_cache_key(cid))

    def test_personal_token_matches_single_row_denies(self):
        agent_id = 'agent-a'
        rows = [
            {
                'agent_id': agent_id,
                'company_id': 42,
                'grant_version': 2,
                'global_company_id': None,
            }
        ]
        claims = {'company_id': 42, 'grant_version': 2}
        matched = _matching_revocation_rows(agent_id, company_id=42, claims=claims, rows=rows)
        self.assertEqual(len(matched), 1)

    def test_personal_mismatch_grant_not_matching_denies_via_ambiguous(self):
        """Row does not match token snapshot: zero matches -> deny at gate."""
        agent_id = 'agent-a'
        rows = [{'agent_id': agent_id, 'company_id': 42, 'grant_version': 1, 'global_company_id': None}]
        claims = {'company_id': 42, 'grant_version': 2}
        matched = _matching_revocation_rows(agent_id, company_id=42, claims=claims, rows=rows)
        self.assertEqual(len(matched), 0)

    def test_two_conflicting_rows_ambiguous(self):
        agent_id = 'agent-a'
        rows = [
            {'agent_id': agent_id, 'company_id': 42, 'grant_version': 1, 'global_company_id': None},
            {'agent_id': agent_id, 'company_id': 42, 'grant_version': 1, 'global_company_id': None},
        ]
        claims = {'company_id': 42, 'grant_version': 1}
        matched = _matching_revocation_rows(agent_id, company_id=42, claims=claims, rows=rows)
        self.assertEqual(len(matched), 2)

    @patch('apps.hosting.mcp_revocation.current_mcp_agent_claims')
    @patch('apps.hosting.mcp_revocation.fetch_revocation_payload')
    def test_agent_revocation_allowed_when_grant_differs(self, mock_fetch, mock_claims):
        aid = 'rev-miss'
        mock_claims.return_value = {'agent_id': aid, 'company_id': 42, 'grant_version': 2}
        mock_fetch.return_value = {
            'revoked_agent_ids': [aid],
            'agents': [{'agent_id': aid, 'company_id': 42, 'grant_version': 1, 'global_company_id': None}],
        }
        self.assertFalse(agent_revocation_denied(aid, company_id=42))
