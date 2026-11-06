"""Live delegated RegionalAgent authority check via Identity (service-signed)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from shellui_django.mcp.internal import (
    REVOCATION_CACHE_SECONDS,
    build_mcp_revocation_assertion,
)

from apps.authapi.mcp_authority import (
    MCP_AUTHORITY_DELEGATED,
    global_company_id_in_claims,
    mcp_authority_mode,
    parse_agent_regional_company_id,
    parse_company_binding_version_claim,
    parse_json_integer_non_negative,
    parse_personal_grant_version,
)
from config.service_signing import signing_kwargs

logger = logging.getLogger(__name__)

_DELEGATED_AUTH_CACHE_PREFIX = "hosting:mcp:delegated_auth:v1:"
_DELEGATED_AUTH_GEN_KEY = "hosting:mcp:delegated_auth:gen"


def _delegated_cache_generation() -> int:
    raw = cache.get(_DELEGATED_AUTH_GEN_KEY)
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def bump_delegated_authority_cache_on_identity_failure() -> None:
    """Invalidate positive delegated-authority cache entries when Identity is unreachable."""
    g = _delegated_cache_generation()
    cache.set(_DELEGATED_AUTH_GEN_KEY, g + 1, timeout=None)


def _cache_ttl_seconds() -> int:
    return min(5, int(REVOCATION_CACHE_SECONDS))


def _service_base_url() -> str:
    return (getattr(settings, "IDENTITY_SERVICE_URL", None) or getattr(settings, "IDENTITY_ISSUER", None) or "").rstrip(
        "/"
    )


def _identity_audience_url() -> str:
    return (getattr(settings, "IDENTITY_ISSUER", None) or getattr(settings, "IDENTITY_SERVICE_URL", None) or "").rstrip(
        "/"
    )


def _delegated_authority_cache_key(
    *,
    agent_id: str,
    company_id: int,
    global_company_id: str,
    grant_version: int,
    company_binding_version: int,
) -> str:
    gen = _delegated_cache_generation()
    h = hashlib.sha256(
        f"{gen}|{agent_id}|{company_id}|{global_company_id}|{grant_version}|{company_binding_version}".encode()
    ).hexdigest()[:32]
    return f"{_DELEGATED_AUTH_CACHE_PREFIX}{h}"


def delegated_live_authority_ok(claims: dict[str, Any] | None) -> bool:
    """True only when Identity confirms an active delegated row matching the token triplet."""
    if not isinstance(claims, dict):
        return False
    if mcp_authority_mode(claims) != MCP_AUTHORITY_DELEGATED:
        return True
    gid = global_company_id_in_claims(claims)
    if gid is None:
        return True
    try:
        agent_id = str(claims.get("agent_id") or "").strip()
        company_id = parse_agent_regional_company_id(claims.get("company_id"))
        gv = parse_personal_grant_version(claims)
        cbv = parse_company_binding_version_claim(claims)
    except (TypeError, ValueError):
        return False
    if not agent_id or gv is None or cbv is None:
        return False

    cache_key = _delegated_authority_cache_key(
        agent_id=agent_id,
        company_id=company_id,
        global_company_id=gid,
        grant_version=gv,
        company_binding_version=cbv,
    )
    cached = cache.get(cache_key)
    if cached is True:
        return True
    if cached is False:
        return False

    base = _service_base_url()
    origin = _identity_audience_url()
    if not base or not origin:
        return False
    path = getattr(
        settings,
        "IDENTITY_DELEGATED_AGENT_AUTHORITY_PATH",
        "/api/v1/mcp/internal/mcp-delegated-agent-authority",
    )
    url = f"{base.rstrip('/')}{path}"
    timeout = min(5.0, float(getattr(settings, "IDENTITY_SYNC_TIMEOUT", 10) or 10))
    try:
        assertion = build_mcp_revocation_assertion(audience_url=origin, **signing_kwargs())
    except Exception:
        logger.warning("Delegated authority assertion rejected: mcp_assertion_rule")
        return False
    body = {
        "agent_id": agent_id,
        "company_id": company_id,
        "global_company_id": gid,
        "grant_version": gv,
        "company_binding_version": cbv,
    }
    try:
        response = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {assertion}"},
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return False
    if response.status_code < 200 or response.status_code > 299:
        return False
    try:
        data = response.json()
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False

    def _bool(key: str) -> bool:
        return data.get(key) is True

    if not _bool("authorized"):
        cache.set(cache_key, False, timeout=_cache_ttl_seconds())
        return False
    if _bool("revoked") or _bool("paused"):
        cache.set(cache_key, False, timeout=_cache_ttl_seconds())
        return False

    try:
        if str(data.get("agent_id") or "").strip() != agent_id:
            return False
        if parse_agent_regional_company_id(data.get("company_id")) != company_id:
            return False
        if global_company_id_in_claims({"global_company_id": data.get("global_company_id")}) != gid:
            return False
        if parse_json_integer_non_negative(data.get("grant_version"), field="grant_version") != gv:
            return False
        if parse_json_integer_non_negative(
            data.get("company_binding_version"), field="company_binding_version"
        ) != cbv:
            return False
    except (TypeError, ValueError):
        return False

    cache.set(cache_key, True, timeout=_cache_ttl_seconds())
    return True
