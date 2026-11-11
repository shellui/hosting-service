"""MCP agent authority: personal regional tokens vs globally delegated (not direct to hosting)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

_GLOBAL_SENTINELS = frozenset({None, ""})

# Identity-issued profile markers (case-insensitive). See Shellui MCP authority contract.
MCP_AUTHORITY_GLOBAL_DELEGATED = "global_delegated"
MCP_AUTHORITY_DELEGATED = "delegated"


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
    return _normalized_global_company_id(claims.get("global_company_id"))


def global_agent_id_in_claims(claims: dict[str, Any] | None) -> str | None:
    """Canonical SaaS ``global_agent_id`` uuid string when Identity issues it on delegated regional tokens."""
    if not isinstance(claims, dict):
        return None
    return _normalized_global_company_id(claims.get("global_agent_id"))


def mcp_authority_mode(claims: dict[str, Any] | None) -> str:
    """Normalized ``mcp_authority`` claim, or empty string when absent."""
    if not isinstance(claims, dict):
        return ""
    return str(claims.get("mcp_authority") or "").strip().lower()


def is_exchange_delegated_regional_agent(claims: dict[str, Any] | None) -> bool:
    """True when ``mcp_authority`` is ``delegated`` and ``global_company_id`` is set (exchange binding).

    Hosting must not create Identity internal approvals for that profile; those approvals belong on the regional AI gateway path.
    """
    if not isinstance(claims, dict):
        return False
    return mcp_authority_mode(claims) == MCP_AUTHORITY_DELEGATED and global_company_id_in_claims(claims) is not None


def strict_non_negative_int_optional(raw: Any, *, field: str) -> int | None:
    """Strict JSON integer for JWT claims: ``int`` only (not bool, str, float)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be a non-negative integer.")
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError(f"{field} must be non-negative.")
        return raw
    raise ValueError(f"{field} must be a non-negative integer.")


def parse_json_integer_non_negative(raw: Any, *, field: str) -> int:
    """Identity HTTP JSON: required non-negative JSON integer."""
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be a non-negative integer.")
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError(f"{field} must be non-negative.")
        return raw
    raise ValueError(f"{field} must be a non-negative integer.")


def parse_personal_grant_version(claims: dict[str, Any] | None) -> int | None:
    """Non-negative int for approval assertions, or None when absent. Raises ValueError if invalid."""
    if not isinstance(claims, dict):
        return None
    return strict_non_negative_int_optional(claims.get("grant_version"), field="grant_version")


def parse_company_binding_version_claim(claims: dict[str, Any] | None) -> int | None:
    """Non-negative int from ``company_binding_version``, or None when absent."""
    if not isinstance(claims, dict):
        return None
    return strict_non_negative_int_optional(
        claims.get("company_binding_version"), field="company_binding_version"
    )


def parse_agent_regional_company_id(raw: Any) -> int:
    """Regional ``company_id`` for agents: required strict non-negative int."""
    val = strict_non_negative_int_optional(raw, field="company_id")
    if val is None:
        raise ValueError("company_id must be a non-negative integer.")
    return val


def parse_delegated_live_authority_company_id(raw: Any) -> int:
    """Regional company id for Identity ``mcp-agent-delegated-authority`` POST: strict positive JSON integer."""
    val = strict_non_negative_int_optional(raw, field="company_id")
    if val is None or val < 1:
        raise ValueError("company_id must be a positive integer.")
    return val


def mcp_personal_agent_rejected(claims: dict[str, Any] | None) -> bool:
    """True when claims are unusable for Identity MCP forwarding (fail closed).

    SaaS global profile (``mcp_authority`` = ``global_delegated``) must not call hosting directly.

    Regional exchanged tokens with ``mcp_authority`` = ``delegated`` may carry a full triplet
    (``global_company_id``, ``grant_version``, ``company_binding_version``) and are allowed when valid.

    Personal regional agents: optional ``grant_version``; ``company_binding_version`` only with delegated triplet.

    Malformed hints (invalid UUID, binding without delegated marker, partial triplet) fail closed.
    """
    if not isinstance(claims, dict):
        return True
    mode = mcp_authority_mode(claims)
    if mode == MCP_AUTHORITY_GLOBAL_DELEGATED:
        return True

    gid = global_company_id_in_claims(claims)
    raw_g = claims.get("global_company_id")
    if raw_g not in _GLOBAL_SENTINELS and gid is None:
        return True

    if gid is not None:
        if mode != MCP_AUTHORITY_DELEGATED:
            return True
        if global_agent_id_in_claims(claims) is None:
            return True
        try:
            gv = parse_personal_grant_version(claims)
            cbv = parse_company_binding_version_claim(claims)
        except ValueError:
            return True
        return gv is None or cbv is None

    bind = claims.get("company_binding_version")
    if bind not in (None, ""):
        return True

    if claims.get("grant_version") in (None, ""):
        return True
    try:
        parse_personal_grant_version(claims)
    except ValueError:
        return True
    return False


def approval_assertion_delegation_kwarg(
    claims: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keyword args for ``build_mcp_approval_assertion`` when the token carries a delegated global triplet."""
    if not isinstance(claims, dict):
        return {}
    if mcp_authority_mode(claims) != MCP_AUTHORITY_DELEGATED:
        return {}
    gid = global_company_id_in_claims(claims)
    if gid is None:
        return {}
    try:
        gv = parse_personal_grant_version(claims)
        cbv = parse_company_binding_version_claim(claims)
    except ValueError:
        return {}
    if gv is None or cbv is None:
        return {}
    return {
        "global_company_id": gid,
        "grant_version": gv,
        "company_binding_version": cbv,
    }


def approval_assertion_grant_kwarg(claims: dict[str, Any] | None) -> dict[str, Any]:
    """Keyword args for ``build_mcp_approval_assertion`` for personal regional agents only.

    If ``grant_version`` is present on the JWT it must parse; do not silently drop it.
    When ``global_company_id`` is set (delegated regional token), delegation kwargs replace grant-only.
    """
    delegated = approval_assertion_delegation_kwarg(claims)
    if delegated:
        return delegated
    if not isinstance(claims, dict):
        return {}
    out: dict[str, Any] = {}
    if "grant_version" not in claims:
        return out
    grant_version = parse_personal_grant_version(claims)
    if grant_version is not None:
        out["grant_version"] = grant_version
    return out
