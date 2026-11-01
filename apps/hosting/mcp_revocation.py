"""Poll Identity for revoked MCP agents (30 s cache)."""

from __future__ import annotations

from django.core.cache import cache

from shellui_mcp.internal import REVOCATION_CACHE_SECONDS

from apps.hosting.mcp_identity import fetch_revocation_payload

_CACHE_KEY = 'hosting:mcp:revoked_agent_ids'
_UNAVAILABLE_KEY = 'hosting:mcp:revocation_unavailable'


def revocation_poll_unavailable() -> bool:
    """True when the latest revocation poll failed (fail closed for MCP)."""
    return cache.get(_UNAVAILABLE_KEY) is True


def agent_revocation_denied(agent_id: str) -> bool:
    """True when Identity revocation is unavailable (fail closed) or the agent is revoked."""
    if revocation_poll_unavailable():
        return True
    ids = _load_blocked_agent_ids()
    if revocation_poll_unavailable():
        return True
    return agent_id in ids


def blocked_agent_ids() -> set[str]:
    if revocation_poll_unavailable():
        return set()
    return _load_blocked_agent_ids()


def _load_blocked_agent_ids() -> set[str]:
    cached = cache.get(_CACHE_KEY)
    if isinstance(cached, list):
        return set(cached)
    payload = fetch_revocation_payload()
    if payload is None:
        cache.set(_UNAVAILABLE_KEY, True, timeout=REVOCATION_CACHE_SECONDS)
        return set()
    cache.set(_UNAVAILABLE_KEY, False, timeout=REVOCATION_CACHE_SECONDS)
    ids = payload.get('revoked_agent_ids') or []
    cache.set(_CACHE_KEY, list(ids), timeout=REVOCATION_CACHE_SECONDS)
    return {str(item) for item in ids}
