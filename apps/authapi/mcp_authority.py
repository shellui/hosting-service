"""MCP agent authority: personal regional tokens vs globally delegated (not direct to hosting)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

_GLOBAL_SENTINELS = frozenset({None, ''})


def _normalized_global_company_id(raw: Any) -> str | None:
    if raw in _GLOBAL_SENTINELS:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return str(UUID(s))
    except ValueError:
        return None


def global_company_id_in_claims(claims: dict[str, Any] | None) -> str | None:
    """Return canonical UUID string if present and valid, else None (absent or invalid)."""
    if not isinstance(claims, dict):
        return None
    return _normalized_global_company_id(claims.get('global_company_id'))


def mcp_personal_agent_rejected(claims: dict[str, Any] | None) -> bool:
    """True when this agent must not use hosting MCP (fail closed).

    Malformed global delegation hints on a direct regional token fail closed.

    Personal regional agents: reject malformed authority hints (binding version without a global id,
    or invalid ``grant_version``). Optional ``grant_version`` must be a non-negative int when
    present; ``0`` is valid. Missing ``grant_version`` is allowed for legacy personal tokens.
    """
    if not isinstance(claims, dict):
        return True
    gid = global_company_id_in_claims(claims)
    raw_g = claims.get('global_company_id')
    if raw_g not in _GLOBAL_SENTINELS and gid is None:
        return True

    bind = claims.get('company_binding_version')
    has_bind = bind is not None and bind != ''
    if has_bind:
        return True

    if claims.get('grant_version') in (None, ''):
        return False
    try:
        parse_personal_grant_version(claims)
    except ValueError:
        return True
    return False


def strict_non_negative_int_optional(raw: Any, *, field: str) -> int | None:
    """JSON-style non-negative int only: int (not bool), or decimal digit string. Rejects float and ``True``/``False``."""
    if raw is None or raw == '':
        return None
    if isinstance(raw, bool):
        raise ValueError(f'{field} must be a non-negative integer.')
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError(f'{field} must be non-negative.')
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s.isdigit():
            raise ValueError(f'{field} must be a non-negative integer.')
        return int(s)
    raise ValueError(f'{field} must be a non-negative integer.')


def parse_personal_grant_version(claims: dict[str, Any] | None) -> int | None:
    """Non-negative int for approval assertions, or None when absent. Raises ValueError if invalid."""
    if not isinstance(claims, dict):
        return None
    return strict_non_negative_int_optional(claims.get('grant_version'), field='grant_version')


def parse_company_binding_version_claim(claims: dict[str, Any] | None) -> int | None:
    """Non-negative int from ``company_binding_version``, or None when absent."""
    if not isinstance(claims, dict):
        return None
    return strict_non_negative_int_optional(claims.get('company_binding_version'), field='company_binding_version')


def parse_agent_regional_company_id(raw: Any) -> int:
    """Regional ``company_id`` for agents: required strict non-negative int."""
    val = strict_non_negative_int_optional(raw, field='company_id')
    if val is None:
        raise ValueError('company_id must be a non-negative integer.')
    return val


def authority_context_for_call_log(claims: dict[str, Any] | None) -> dict[str, Any]:
    """Actor-derived grant or binding context for Identity call logs (no client-supplied text)."""
    if not isinstance(claims, dict):
        return {}
    out: dict[str, Any] = {}
    try:
        gv = parse_personal_grant_version(claims)
        if gv is not None:
            out['grant_version'] = gv
    except ValueError:
        pass
    try:
        cbv = parse_company_binding_version_claim(claims)
        if cbv is not None:
            out['company_binding_version'] = cbv
    except ValueError:
        pass
    gid = global_company_id_in_claims(claims)
    if gid is not None:
        out['global_company_id'] = gid
    return out


def approval_assertion_grant_kwarg(claims: dict[str, Any] | None) -> dict[str, Any]:
    """Keyword args for ``build_mcp_approval_assertion`` for personal regional agents only.

    If ``grant_version`` is present on the JWT it must parse; do not silently drop it.
    """
    if not isinstance(claims, dict):
        return {}
    out: dict[str, Any] = {}
    if 'grant_version' not in claims:
        return out
    grant_version = parse_personal_grant_version(claims)
    if grant_version is not None:
        out['grant_version'] = grant_version
    return out
