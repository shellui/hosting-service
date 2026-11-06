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

    Globally delegated agents (valid ``global_company_id`` on the JWT) never call hosting
    directly; reject even if a gateway bug forwards the token.

    Personal regional agents: reject malformed authority hints (binding version without a global id,
    or invalid ``grant_version``). Optional ``grant_version`` must be a non-negative int when
    present; ``0`` is valid. Missing ``grant_version`` is allowed for legacy personal tokens.
    """
    if not isinstance(claims, dict):
        return True
    gid = global_company_id_in_claims(claims)
    if gid is not None:
        return True
    raw_g = claims.get('global_company_id')
    if raw_g not in _GLOBAL_SENTINELS and gid is None:
        return True

    bind = claims.get('company_binding_version')
    has_bind = bind is not None and bind != ''
    if has_bind:
        return True

    gv = claims.get('grant_version')
    if gv is None:
        return False
    if isinstance(gv, bool):
        return True
    if isinstance(gv, int):
        return gv < 0
    if isinstance(gv, str):
        s = gv.strip()
        if not s.isdigit():
            return True
        return int(s) < 0
    return True


def parse_personal_grant_version(claims: dict[str, Any] | None) -> int | None:
    """Non-negative int for approval assertions, or None when absent. Raises ValueError if invalid."""
    if not isinstance(claims, dict):
        return None
    gv = claims.get('grant_version')
    if gv is None:
        return None
    if isinstance(gv, bool):
        raise ValueError('grant_version must be a non-negative integer.')
    if isinstance(gv, int):
        if gv < 0:
            raise ValueError('grant_version must be non-negative.')
        return gv
    if isinstance(gv, str):
        s = gv.strip()
        if not s.isdigit():
            raise ValueError('grant_version must be a non-negative integer.')
        return int(s)
    raise ValueError('grant_version must be a non-negative integer.')


def approval_assertion_grant_kwarg(claims: dict[str, Any] | None) -> dict[str, Any]:
    """Keyword args for ``build_mcp_approval_assertion`` for personal regional agents only."""
    try:
        grant_version = parse_personal_grant_version(claims)
    except ValueError:
        grant_version = None
    out: dict[str, Any] = {}
    if grant_version is not None:
        out['grant_version'] = grant_version
    return out
