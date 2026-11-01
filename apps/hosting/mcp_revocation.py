"""Poll Identity for revoked MCP agents (30 s cache)."""

from __future__ import annotations

from django.core.cache import cache

from shellui_mcp.internal import REVOCATION_CACHE_SECONDS

from apps.hosting.mcp_identity import fetch_revocation_payload

_CACHE_KEY = 'hosting:mcp:revoked_agent_ids'


def blocked_agent_ids() -> set[str]:
    cached = cache.get(_CACHE_KEY)
    if isinstance(cached, list):
        return set(cached)
    payload = fetch_revocation_payload()
    if payload is None:
        return set()
    ids = payload.get('revoked_agent_ids') or []
    cache.set(_CACHE_KEY, list(ids), timeout=REVOCATION_CACHE_SECONDS)
    return {str(item) for item in ids}
