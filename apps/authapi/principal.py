"""Authenticated principal extracted from identity-service JWTs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.authapi.mcp_authority import (
    MCP_AUTHORITY_DELEGATED,
    MCP_AUTHORITY_GLOBAL_DELEGATED,
    global_agent_id_in_claims,
    global_company_id_in_claims,
    mcp_authority_mode,
    parse_agent_regional_company_id,
    parse_company_binding_version_claim,
    parse_personal_grant_version,
)


@dataclass
class HostingPrincipal:
    """Lightweight stand-in for Django's User, built from JWT claims."""

    user_id: int
    company_id: int | None
    email: str = ""
    username: str = ""
    is_staff: bool = False
    is_company_owner: bool = False
    access_global_metrics: bool = False
    # Set when the request used a company deploy token (preview deploys only).
    deploy_token_id: str | None = None
    agent_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def pk(self) -> int:
        return self.user_id

    @property
    def id(self) -> int:
        return self.user_id

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def __str__(self) -> str:
        return self.email or self.username or str(self.user_id)


def _agent_owner_user_id(claims: dict[str, Any]) -> int:
    """Regional user id of the member who approved the agent.

    Identity puts that id in ``owner_user_id``. The claim is omitted when the
    agent has no user. It is not a company-owner flag.
    """
    raw = claims.get("owner_user_id")
    if raw in (None, ""):
        return 0
    if isinstance(raw, bool):
        raise ValueError("Agent JWT owner_user_id must be a non-negative integer.")
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError("Agent JWT owner_user_id must be a non-negative integer.")
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    raise ValueError("Agent JWT owner_user_id must be a non-negative integer.")


def _agent_claims(claims: dict[str, Any]) -> dict[str, Any]:
    """Copy claims and treat a missing ``mcp_access`` as read-only."""
    stored = dict(claims)
    raw_access = stored.get("mcp_access")
    if raw_access in (None, ""):
        stored["mcp_access"] = "read_only"
    else:
        stored["mcp_access"] = str(raw_access).strip().lower()
    return stored


def principal_from_claims(claims: dict[str, Any]) -> HostingPrincipal:
    sub = str(claims.get("sub") or "")
    if sub.startswith("agent:"):
        agent_id = str(claims.get("agent_id") or sub.split(":", 1)[1])
        raw_company = claims.get("company_id")
        if raw_company in (None, ""):
            raise ValueError("Agent JWT is missing company_id.")
        try:
            company_id = parse_agent_regional_company_id(raw_company)
        except ValueError as exc:
            raise ValueError(
                "Agent JWT company_id must be a non-negative integer."
            ) from exc
        raw_global = claims.get("global_company_id")
        mode = mcp_authority_mode(claims)
        if raw_global not in (None, ""):
            gid = global_company_id_in_claims(claims)
            if gid is None:
                raise ValueError("mcp_authority_global_company_id_invalid")
            if mode == MCP_AUTHORITY_GLOBAL_DELEGATED:
                raise ValueError("mcp_authority_global_delegated_on_direct_resource")
            if mode == MCP_AUTHORITY_DELEGATED:
                try:
                    gv = parse_personal_grant_version(claims)
                    cbv = parse_company_binding_version_claim(claims)
                except ValueError as exc:
                    raise ValueError("mcp_authority_delegated_triplet_invalid") from exc
                if gv is None or cbv is None:
                    raise ValueError("mcp_authority_delegated_triplet_incomplete")
                if global_agent_id_in_claims(claims) is None:
                    raise ValueError("mcp_authority_global_agent_id_invalid")
            else:
                raise ValueError("mcp_authority_delegated_on_direct_resource")
        elif claims.get("company_binding_version") not in (None, ""):
            raise ValueError("mcp_authority_binding_without_global")
        if raw_global in (None, "") and claims.get("grant_version") in (None, ""):
            raise ValueError("mcp_authority_grant_version_required")
        try:
            parse_personal_grant_version(claims)
        except ValueError as exc:
            raise ValueError("mcp_authority_grant_version_invalid") from exc
        # The member id is owner_user_id. Agent tokens are never staff and
        # never company owners, including when user_metadata says otherwise.
        return HostingPrincipal(
            user_id=_agent_owner_user_id(claims),
            company_id=company_id,
            is_staff=False,
            is_company_owner=False,
            agent_id=agent_id,
            claims=_agent_claims(claims),
        )

    user_metadata = claims.get("user_metadata") or {}
    if not isinstance(user_metadata, dict):
        user_metadata = {}

    raw_uid = claims.get("user_id", claims.get("sub"))
    try:
        user_id = int(raw_uid)
    except (TypeError, ValueError) as exc:
        raise ValueError("JWT is missing a numeric user id / sub claim.") from exc

    raw_company = claims.get("company_id")
    company_id: int | None
    if raw_company in (None, ""):
        company_id = None
    else:
        try:
            company_id = int(raw_company)
        except (TypeError, ValueError) as exc:
            raise ValueError("JWT company_id must be an integer.") from exc

    return HostingPrincipal(
        user_id=user_id,
        company_id=company_id,
        email=str(claims.get("email") or user_metadata.get("email") or ""),
        username=str(claims.get("username") or user_metadata.get("username") or ""),
        is_staff=bool(user_metadata.get("is_staff", False)),
        is_company_owner=bool(user_metadata.get("is_company_owner", False)),
        access_global_metrics=bool(claims.get("pat_agm", False)),
        claims=claims,
    )
