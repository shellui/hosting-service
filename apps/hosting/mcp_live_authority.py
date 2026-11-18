"""Live delegated RegionalAgent authority check via Identity (service-signed)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from shellui_django.mcp.internal import InternalAssertionError

from apps.authapi.mcp_authority import (
    MCP_AUTHORITY_DELEGATED,
    global_agent_id_in_claims,
    global_company_id_in_claims,
    mcp_authority_mode,
    parse_company_binding_version_claim,
    parse_delegated_live_authority_company_id,
    parse_json_integer_non_negative,
    parse_personal_grant_version,
)
from config.service_signing import build_mcp_delegated_agent_authority_assertion

logger = logging.getLogger(__name__)

_DELEGATED_AUTH_CACHE_PREFIX = "hosting:mcp:delegated_auth:v1:"
_DELEGATED_AUTH_GEN_KEY = "hosting:mcp:delegated_auth:gen"

# Reason from ``delegated_live_authority_state`` for HTTP mapping on the MCP edge.
DELEGATED_AUTH_REASON_SKIP = "skip"
DELEGATED_AUTH_REASON_OK = "ok"
DELEGATED_AUTH_REASON_DENY = "deny"
DELEGATED_AUTH_REASON_UNAVAILABLE = "unavailable"
DELEGATED_AUTH_REASON_MISCONFIGURED = "misconfigured"

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
    from shellui_django.mcp.internal import REVOCATION_CACHE_SECONDS

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


def _strict_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean.")


def _scope_service_ids(claims: dict[str, Any]) -> frozenset[str]:
    raw = claims.get("scope")
    if raw is None or raw == "":
        return frozenset()
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split() if p.strip()]
        return frozenset(parts)
    if isinstance(raw, (list, tuple)):
        return frozenset(str(p).strip() for p in raw if str(p).strip())
    return frozenset()


# Identity ``_delegated_authority_fixed_payload`` (see identity-service ``internal_views.py``): fixed 15 keys; ``revoked_at`` may be null.
_FIXED_DELEGATED_AUTHORITY_200_KEYS = frozenset(
    {
        "authorized",
        "active",
        "revoked",
        "paused",
        "agent_id",
        "company_id",
        "global_agent_id",
        "global_company_id",
        "grant_version",
        "company_binding_version",
        "access_mode",
        "read_level",
        "allow_destructive",
        "services_allowed",
        "revoked_at",
    }
)


def _jwt_access_mode(claims: dict[str, Any]) -> str:
    return str(claims.get("mcp_access") or "read_only").strip().lower() or "read_only"


def _jwt_read_level(claims: dict[str, Any]) -> str:
    return str(claims.get("mcp_read") or "safe").strip().lower() or "safe"


def _jwt_allow_destructive(claims: dict[str, Any]) -> bool:
    return claims.get("mcp_destructive") is True


def _identity_services_allowed_list(raw: Any) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None
        s = item.strip()
        if s:
            out.append(s)
    return sorted(out)


def _delegated_identity_200_ok(data: dict[str, Any], claims: dict[str, Any]) -> bool:
    """Validate Identity fixed-shape **200** for ``mcp-agent-delegated-authority`` (live or binding mismatch)."""
    if set(data.keys()) != _FIXED_DELEGATED_AUTHORITY_200_KEYS:
        return False

    try:
        authorized = _strict_bool(data.get("authorized"), field="authorized")
        active = _strict_bool(data.get("active"), field="active")
        revoked = _strict_bool(data.get("revoked"), field="revoked")
        paused = _strict_bool(data.get("paused"), field="paused")
        allow_dest = _strict_bool(data.get("allow_destructive"), field="allow_destructive")
    except ValueError:
        return False

    if allow_dest is not False:
        return False

    agent_id = str(claims.get("agent_id") or "").strip()
    company_id = parse_delegated_live_authority_company_id(claims.get("company_id"))
    gv = parse_personal_grant_version(claims)
    cbv = parse_company_binding_version_claim(claims)
    gid = global_company_id_in_claims(claims)
    gaid = global_agent_id_in_claims(claims)
    if gv is None or cbv is None or gid is None or gaid is None:
        return False

    scope_ids = _scope_service_ids(claims)
    if not scope_ids or "hosting" not in scope_ids:
        return False

    rat = data.get("revoked_at")
    if rat is not None:
        try:
            parse_json_integer_non_negative(rat, field="revoked_at")
        except (TypeError, ValueError):
            return False

    access_mode_row = str(data.get("access_mode") or "").strip().lower()
    read_level_row = str(data.get("read_level") or "").strip().lower()
    if access_mode_row != _jwt_access_mode(claims) or read_level_row != _jwt_read_level(claims):
        return False
    if _jwt_allow_destructive(claims):
        return False

    sv_row = _identity_services_allowed_list(data.get("services_allowed"))
    if sv_row is None:
        return False
    for svc in scope_ids:
        if svc not in sv_row:
            return False

    try:
        if str(data.get("agent_id") or "").strip() != agent_id:
            return False
        if global_company_id_in_claims({"global_company_id": data.get("global_company_id")}) != gid:
            return False
        if global_agent_id_in_claims({"global_agent_id": data.get("global_agent_id")}) != gaid:
            return False
        if parse_delegated_live_authority_company_id(data.get("company_id")) != company_id:
            return False
        if parse_json_integer_non_negative(data.get("grant_version"), field="grant_version") != gv:
            return False
        if parse_json_integer_non_negative(data.get("company_binding_version"), field="company_binding_version") != cbv:
            return False
    except (TypeError, ValueError):
        return False

    if not authorized:
        return False

    if not active or revoked or paused:
        logger.info(
            "Delegated agent authority denied by Identity snapshot: authorized=%s active=%s revoked=%s paused=%s",
            authorized,
            active,
            revoked,
            paused,
        )
        return False

    return True


def delegated_live_authority_state(claims: dict[str, Any] | None) -> tuple[str, bool]:
    """Return (reason, allowed). ``skip`` when no live delegated check applies."""
    if not isinstance(claims, dict):
        return DELEGATED_AUTH_REASON_DENY, False
    if mcp_authority_mode(claims) != MCP_AUTHORITY_DELEGATED:
        return DELEGATED_AUTH_REASON_SKIP, True
    gid = global_company_id_in_claims(claims)
    if gid is None:
        return DELEGATED_AUTH_REASON_SKIP, True
    try:
        agent_id = str(claims.get("agent_id") or "").strip()
        company_id = parse_delegated_live_authority_company_id(claims.get("company_id"))
        gv = parse_personal_grant_version(claims)
        cbv = parse_company_binding_version_claim(claims)
    except (TypeError, ValueError):
        return DELEGATED_AUTH_REASON_DENY, False
    gaid = global_agent_id_in_claims(claims)
    if not agent_id or gv is None or cbv is None or gaid is None:
        return DELEGATED_AUTH_REASON_DENY, False

    cache_key = _delegated_authority_cache_key(
        agent_id=agent_id,
        company_id=company_id,
        global_company_id=gid,
        grant_version=gv,
        company_binding_version=cbv,
    )
    cached = cache.get(cache_key)
    if cached is True:
        return DELEGATED_AUTH_REASON_OK, True
    if cached is False:
        return DELEGATED_AUTH_REASON_DENY, False

    base = _service_base_url()
    origin = _identity_audience_url()
    if not base or not origin:
        return DELEGATED_AUTH_REASON_MISCONFIGURED, False

    path = getattr(
        settings,
        "IDENTITY_DELEGATED_AGENT_AUTHORITY_PATH",
        "/api/v1/mcp/internal/mcp-agent-delegated-authority",
    )
    url = f"{base.rstrip('/')}{path}"
    timeout = min(5.0, float(getattr(settings, "IDENTITY_SYNC_TIMEOUT", 10) or 10))
    try:
        assertion = build_mcp_delegated_agent_authority_assertion(audience_url=origin)
    except InternalAssertionError as exc:
        if getattr(exc, "status", None) == 503:
            logger.warning("Delegated authority assertion rejected: mcp_assertion_rule")
            return DELEGATED_AUTH_REASON_UNAVAILABLE, False
        logger.warning("Delegated authority assertion rejected: mcp_assertion_rule")
        return DELEGATED_AUTH_REASON_DENY, False
    except Exception:
        logger.warning("Delegated authority assertion failed: mcp_assertion_error")
        return DELEGATED_AUTH_REASON_DENY, False

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
    except OSError:
        bump_delegated_authority_cache_on_identity_failure()
        return DELEGATED_AUTH_REASON_UNAVAILABLE, False
    except Exception:
        bump_delegated_authority_cache_on_identity_failure()
        return DELEGATED_AUTH_REASON_UNAVAILABLE, False

    if response.status_code == 401:
        return DELEGATED_AUTH_REASON_DENY, False
    if response.status_code == 400:
        cache.set(cache_key, False, timeout=_cache_ttl_seconds())
        return DELEGATED_AUTH_REASON_DENY, False
    if response.status_code == 503 or response.status_code == 502 or response.status_code == 504:
        bump_delegated_authority_cache_on_identity_failure()
        return DELEGATED_AUTH_REASON_UNAVAILABLE, False
    if response.status_code == 404:
        try:
            err_body = response.json()
        except ValueError:
            bump_delegated_authority_cache_on_identity_failure()
            return DELEGATED_AUTH_REASON_UNAVAILABLE, False
        if isinstance(err_body, dict) and err_body.get('error'):
            cache.set(cache_key, False, timeout=_cache_ttl_seconds())
            return DELEGATED_AUTH_REASON_DENY, False
        bump_delegated_authority_cache_on_identity_failure()
        return DELEGATED_AUTH_REASON_UNAVAILABLE, False
    if response.status_code == 403:
        cache.set(cache_key, False, timeout=_cache_ttl_seconds())
        return DELEGATED_AUTH_REASON_DENY, False
    if response.status_code < 200 or response.status_code > 299:
        bump_delegated_authority_cache_on_identity_failure()
        return DELEGATED_AUTH_REASON_UNAVAILABLE, False

    try:
        data = response.json()
    except ValueError:
        bump_delegated_authority_cache_on_identity_failure()
        return DELEGATED_AUTH_REASON_UNAVAILABLE, False
    if not isinstance(data, dict):
        bump_delegated_authority_cache_on_identity_failure()
        return DELEGATED_AUTH_REASON_UNAVAILABLE, False

    if not _delegated_identity_200_ok(data, claims):
        cache.set(cache_key, False, timeout=_cache_ttl_seconds())
        return DELEGATED_AUTH_REASON_DENY, False

    cache.set(cache_key, True, timeout=_cache_ttl_seconds())
    return DELEGATED_AUTH_REASON_OK, True


def delegated_live_authority_ok(claims: dict[str, Any] | None) -> bool:
    """True only when Identity confirms an active delegated row matching the token triplet."""
    _reason, allowed = delegated_live_authority_state(claims)
    return allowed
