"""Poll Identity for revoked MCP agents (30 s cache)."""

from __future__ import annotations

from typing import Any

from django.core.cache import cache
from shellui_django.mcp.internal import REVOCATION_CACHE_SECONDS

from apps.authapi.mcp_authority import (
    MCP_AUTHORITY_DELEGATED,
    global_company_id_in_claims,
    mcp_authority_mode,
    parse_company_binding_version_claim,
    parse_personal_grant_version,
    strict_non_negative_int_optional,
)
from apps.hosting.mcp_context import current_mcp_agent_claims
from apps.hosting.mcp_identity import fetch_revocation_payload

_INVALID = object()


def _row_non_negative(raw: Any, *, field: str) -> int | None | object:
    if raw in (None, ""):
        return None
    try:
        return strict_non_negative_int_optional(raw, field=field)
    except ValueError:
        return _INVALID


def _cache_key(company_id: int | None) -> str:
    if company_id is None:
        return "hosting:mcp:revoked_agent_ids:all"
    return f"hosting:mcp:revoked_agent_ids:{int(company_id)}"


def _agents_cache_key(company_id: int | None) -> str:
    return f"{_cache_key(company_id)}:agents"


def _unavailable_key(company_id: int | None) -> str:
    if company_id is None:
        return "hosting:mcp:revocation_unavailable:all"
    return f"hosting:mcp:revocation_unavailable:{int(company_id)}"


def _agent_company_id() -> int | None:
    claims = current_mcp_agent_claims() or {}
    raw = claims.get("company_id")
    if raw in (None, ""):
        return None
    try:
        v = strict_non_negative_int_optional(raw, field="company_id")
    except ValueError:
        return None
    return v


def revocation_poll_unavailable(*, company_id: int | None = None) -> bool:
    """True when the latest revocation poll failed (fail closed for MCP)."""
    if company_id is None:
        company_id = _agent_company_id()
    return cache.get(_unavailable_key(company_id)) is True


def _row_global_uuid(row: dict[str, Any]) -> str | None:
    return global_company_id_in_claims(
        {"global_company_id": row.get("global_company_id")}
    )


def _matching_revocation_rows(
    agent_id: str,
    *,
    company_id: int,
    claims: dict[str, Any],
    rows: list,
) -> list[dict[str, Any]]:
    """Rows that exactly match this token's agent, regional company, and authority snapshot (no ``[0]`` fallback)."""
    try:
        jwt_grant = parse_personal_grant_version(claims)
    except ValueError:
        return []
    try:
        jwt_cbv = parse_company_binding_version_claim(claims)
    except ValueError:
        return []

    jwt_gid = global_company_id_in_claims(claims)

    matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("agent_id")) != str(agent_id):
            continue
        rc = _row_non_negative(row.get("company_id"), field="company_id")
        if rc is _INVALID or rc != company_id:
            continue
        rgv = _row_non_negative(row.get("grant_version"), field="grant_version")
        if rgv is _INVALID:
            continue
        rcbv = _row_non_negative(
            row.get("company_binding_version"), field="company_binding_version"
        )
        if rcbv is _INVALID:
            continue
        row_global = _row_global_uuid(row)
        if row_global is None and (row.get("global_company_id") not in (None, "")):
            # Malformed global hint on row
            continue

        if jwt_gid is None:
            # Personal regional: row must not assert global delegation.
            if row_global is not None:
                continue
            if jwt_grant is None:
                if rgv is not None:
                    continue
            else:
                if rgv != jwt_grant:
                    continue
            if jwt_cbv is None:
                if rcbv is not None:
                    continue
            else:
                if rcbv != jwt_cbv:
                    continue
        else:
            # Delegated: require full match including canonical global UUID.
            if row_global != jwt_gid:
                continue
            if jwt_grant is None:
                if rgv is not None:
                    continue
            else:
                if rgv != jwt_grant:
                    continue
            if jwt_cbv is None:
                if rcbv is not None:
                    continue
            else:
                if rcbv != jwt_cbv:
                    continue
        matches.append(row)
    return matches


def _revoke_applies_to_current_token(
    agent_id: str,
    *,
    company_id: int | None,
    agents: list,
    claims: dict | None,
) -> bool:
    """True when a revocation list entry applies to this MCP token (deny the request)."""
    claims = claims if isinstance(claims, dict) else {}
    jwt_gid = global_company_id_in_claims(claims)
    if jwt_gid is not None and mcp_authority_mode(claims) != MCP_AUTHORITY_DELEGATED:
        # Global-only profile or unmarked global hint: deny even if the id is listed.
        return True
    if company_id is None:
        return True
    rows = [row for row in agents if isinstance(row, dict)]
    id_rows = [row for row in rows if str(row.get("agent_id")) == str(agent_id)]
    if not id_rows:
        # Id listed but no per-agent rows: treat as revoked (fail closed).
        return True
    matching = _matching_revocation_rows(
        agent_id, company_id=company_id, claims=claims, rows=id_rows
    )
    if len(matching) != 1:
        # Absent or ambiguous match for this token vs live rows: fail closed.
        return True
    row = matching[0]
    # True when Identity marks this snapshot rejected; otherwise the listed id does not revoke this token.
    return bool(row.get("mcp_authority_snapshot_rejected"))


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
    return _revoke_applies_to_current_token(
        agent_id, company_id=company_id, agents=agents, claims=claims
    )


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
    ids = payload.get("revoked_agent_ids") or []
    agents = payload.get("agents") or []
    cache.set(cache_key, list(ids), timeout=REVOCATION_CACHE_SECONDS)
    cache.set(_agents_cache_key(company_id), agents, timeout=REVOCATION_CACHE_SECONDS)
    return {str(item) for item in ids}
