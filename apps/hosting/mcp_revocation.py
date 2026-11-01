"""Poll Identity for revoked MCP agents (30 s cache)."""

from __future__ import annotations

from django.core.cache import cache

from shellui_mcp.internal import REVOCATION_CACHE_SECONDS

from apps.hosting.mcp_context import current_mcp_agent_claims
from apps.hosting.mcp_identity import fetch_revocation_payload


def _cache_key(company_id: int | None) -> str:
    if company_id is None:
        return 'hosting:mcp:revoked_agent_ids:all'
    return f'hosting:mcp:revoked_agent_ids:{int(company_id)}'


def _agents_cache_key(company_id: int | None) -> str:
    return f'{_cache_key(company_id)}:agents'


def _unavailable_key(company_id: int | None) -> str:
    if company_id is None:
        return 'hosting:mcp:revocation_unavailable:all'
    return f'hosting:mcp:revocation_unavailable:{int(company_id)}'


def _agent_company_id() -> int | None:
    claims = current_mcp_agent_claims() or {}
    raw = claims.get('company_id')
    if raw in (None, ''):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def revocation_poll_unavailable() -> bool:
    """True when the latest revocation poll failed (fail closed for MCP)."""
    return cache.get(_unavailable_key(_agent_company_id())) is True


def _agent_company_binding_ok(agent_id: str, *, company_id: int | None, agents: list) -> bool:
    if company_id is None:
        return True
    for row in agents:
        if not isinstance(row, dict):
            continue
        if str(row.get('agent_id')) != str(agent_id):
            continue
        try:
            return int(row.get('company_id')) == int(company_id)
        except (TypeError, ValueError):
            return False
    return True


def agent_revocation_denied(agent_id: str) -> bool:
    """True when Identity revocation is unavailable (fail closed) or the agent is revoked."""
    if revocation_poll_unavailable():
        return True
    company_id = _agent_company_id()
    ids = _load_blocked_agent_ids()
    if revocation_poll_unavailable():
        return True
    if agent_id not in ids:
        return False
    agents = cache.get(_agents_cache_key(company_id)) or []
    if not _agent_company_binding_ok(agent_id, company_id=company_id, agents=agents):
        return True
    return True


def blocked_agent_ids() -> set[str]:
    if revocation_poll_unavailable():
        return set()
    return _load_blocked_agent_ids()


def _load_blocked_agent_ids() -> set[str]:
    company_id = _agent_company_id()
    cache_key = _cache_key(company_id)
    unavailable_key = _unavailable_key(company_id)
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        return {str(item) for item in cached}
    payload = fetch_revocation_payload(company_id=company_id)
    if payload is None:
        cache.set(unavailable_key, True, timeout=REVOCATION_CACHE_SECONDS)
        return set()
    cache.set(unavailable_key, False, timeout=REVOCATION_CACHE_SECONDS)
    ids = payload.get('revoked_agent_ids') or []
    agents = payload.get('agents') or []
    cache.set(cache_key, list(ids), timeout=REVOCATION_CACHE_SECONDS)
    cache.set(_agents_cache_key(company_id), agents, timeout=REVOCATION_CACHE_SECONDS)
    return {str(item) for item in ids}
