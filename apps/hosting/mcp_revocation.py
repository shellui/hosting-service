"""Poll Identity for revoked MCP agents (30 s cache)."""

from __future__ import annotations

from django.core.cache import cache

from shellui_django.mcp.internal import REVOCATION_CACHE_SECONDS

from apps.authapi.mcp_authority import global_company_id_in_claims, parse_personal_grant_version
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


def revocation_poll_unavailable(*, company_id: int | None = None) -> bool:
    """True when the latest revocation poll failed (fail closed for MCP)."""
    if company_id is None:
        company_id = _agent_company_id()
    return cache.get(_unavailable_key(company_id)) is True


def _revoke_applies_to_current_token(
    agent_id: str,
    *,
    company_id: int | None,
    agents: list,
    claims: dict | None,
) -> bool:
    """True when a revocation list entry applies to this MCP token (deny the request)."""
    claims = claims if isinstance(claims, dict) else {}
    if global_company_id_in_claims(claims):
        # Direct hosting tokens cannot carry delegated global proof; treat as deny.
        return True
    try:
        jwt_grant = parse_personal_grant_version(claims)
    except ValueError:
        return True
    if company_id is None:
        return True
    rows = [row for row in agents if isinstance(row, dict) and str(row.get('agent_id')) == str(agent_id)]
    if not rows:
        # Revoked id with no matching agent row: trust the revoked list.
        return True
    for row in rows:
        if row.get('mcp_authority_snapshot_rejected'):
            return True
        if row.get('global_company_id'):
            continue
        try:
            if int(row.get('company_id')) != int(company_id):
                continue
        except (TypeError, ValueError):
            return True
        rgv = row.get('grant_version')
        if jwt_grant is not None:
            if rgv is None:
                return True
            try:
                if int(rgv) != int(jwt_grant):
                    continue
            except (TypeError, ValueError):
                return True
        else:
            if rgv is not None:
                return True
        return True
    return False


def agent_revocation_denied(agent_id: str, company_id: int | None = None) -> bool:
    """True when Identity revocation is unavailable (fail closed) or the agent is revoked."""
    if company_id is None:
        company_id = _agent_company_id()
    if revocation_poll_unavailable(company_id=company_id):
        return True
    claims = current_mcp_agent_claims()
    ids = _load_revocation_agent_ids(company_id=company_id)
    if revocation_poll_unavailable(company_id=company_id):
        return True
    if agent_id not in ids:
        return False
    agents = cache.get(_agents_cache_key(company_id)) or []
    return _revoke_applies_to_current_token(agent_id, company_id=company_id, agents=agents, claims=claims)


def blocked_agent_ids() -> set[str]:
    if revocation_poll_unavailable():
        return set()
    return _load_revocation_agent_ids()


def _load_revocation_agent_ids(*, company_id: int | None = None) -> set[str]:
    if company_id is None:
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
