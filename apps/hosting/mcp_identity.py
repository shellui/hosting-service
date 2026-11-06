"""Forward MCP approvals and call logs to identity-service."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

from shellui_django.mcp.internal import (
    InternalAssertionError,
    build_mcp_approval_assertion,
    build_mcp_call_log_assertion,
    build_mcp_revocation_assertion,
    parse_trusted_revocation_poll_response,
)
from apps.authapi.mcp_authority import (
    approval_assertion_grant_kwarg,
    is_exchange_delegated_regional_agent,
    mcp_personal_agent_rejected,
    parse_agent_regional_company_id,
)
from apps.hosting.mcp_live_authority import (
    bump_delegated_authority_cache_on_identity_failure,
    delegated_live_authority_ok,
)
from apps.hosting.mcp_call_log_body import build_identity_call_log_body
from apps.hosting.mcp_context import current_mcp_agent_claims
from config.service_signing import signing_kwargs

logger = logging.getLogger(__name__)

APPROVAL_LOOKUP_UNAVAILABLE = '__approval_unavailable__'

_APPROVAL_ROUTE_CONTEXT: dict[str, dict[str, Any]] = {}


def identity_origin_url() -> str:
    return (getattr(settings, 'IDENTITY_ISSUER', None) or getattr(settings, 'IDENTITY_SERVICE_URL', None) or '').rstrip(
        '/'
    )


def identity_service_base_url() -> str:
    return (getattr(settings, 'IDENTITY_SERVICE_URL', None) or identity_origin_url()).rstrip('/')


def _identity_origin() -> str:
    return identity_origin_url()


def _identity_base() -> str:
    return identity_service_base_url()


def create_approval_request(payload: dict) -> dict | None:
    base = _identity_base()
    if not base:
        return None
    claims = current_mcp_agent_claims()
    if is_exchange_delegated_regional_agent(claims):
        return None
    if mcp_personal_agent_rejected(claims):
        return None
    if not delegated_live_authority_ok(claims):
        return None
    agent_id = str(payload.get('agent_id') or '')
    company_id = payload.get('company_id')
    if not agent_id or company_id is None:
        return None
    try:
        co_int = parse_agent_regional_company_id(company_id)
    except ValueError:
        return None
    try:
        assertion = build_mcp_approval_assertion(
            company_id=co_int,
            agent_id=agent_id,
            service=str(payload.get('service') or 'hosting'),
            action=str(payload.get('action') or ''),
            arguments_hash=str(payload.get('arguments_hash') or ''),
            audience_url=_identity_origin(),
            **approval_assertion_grant_kwarg(claims),
            **signing_kwargs(),
        )
    except InternalAssertionError:
        logger.warning('MCP approval assertion rejected: mcp_assertion_rule')
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP approval assertion failed: mcp_assertion_error')
        return None
    url = f'{base}/api/v1/mcp/internal/mcp-approval-requests'
    # Arguments are represented only in the signed assertion (`arguments_hash`); body is empty.
    body: dict[str, Any] = {}
    try:
        response = requests.post(
            url,
            json=body,
            headers={'Authorization': f'Bearer {assertion}'},
            timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10),
        )
        if response.status_code >= 400:
            logger.warning('MCP approval forward failed: HTTP %s', response.status_code)
            return None
        data = response.json()
        return {'id': data.get('id'), 'status': data.get('status')}
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP approval forward error: identity_request_failed')
        return None


def _approval_route_assertion(payload: dict) -> str | None:
    claims = current_mcp_agent_claims()
    if is_exchange_delegated_regional_agent(claims):
        return None
    if mcp_personal_agent_rejected(claims):
        return None
    if not delegated_live_authority_ok(claims):
        return None
    agent_id = str(payload.get('agent_id') or '')
    company_id = payload.get('company_id')
    args_hash = str(payload.get('arguments_hash') or '')
    if not agent_id or company_id is None or not args_hash:
        return None
    try:
        co_int = parse_agent_regional_company_id(company_id)
    except ValueError:
        return None
    try:
        return build_mcp_approval_assertion(
            company_id=co_int,
            agent_id=agent_id,
            service=str(payload.get('service') or 'hosting'),
            action=str(payload.get('action') or ''),
            arguments_hash=args_hash,
            audience_url=_identity_origin(),
            **approval_assertion_grant_kwarg(claims),
            **signing_kwargs(),
        )
    except InternalAssertionError:
        logger.warning('MCP approval assertion rejected: mcp_assertion_rule')
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP approval assertion failed: mcp_assertion_error')
        return None


def lookup_approval_state(payload: dict) -> str | None:
    """Return ``pending``, ``approved``, ``executed``, or None by asking identity-service."""
    base = _identity_base()
    if not base:
        return None
    claims = current_mcp_agent_claims()
    if mcp_personal_agent_rejected(claims):
        return None
    if not delegated_live_authority_ok(claims):
        return None
    assertion = _approval_route_assertion(payload)
    if not assertion:
        return None
    url = f'{base}/api/v1/mcp/internal/mcp-approval-state'
    try:
        response = requests.post(
            url,
            json={},
            headers={'Authorization': f'Bearer {assertion}'},
            timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10),
        )
        if response.status_code == 404 or response.status_code >= 400:
            return APPROVAL_LOOKUP_UNAVAILABLE
        data = response.json()
        status = str(data.get('status') or '')
        if status == 'approved' and data.get('id'):
            approval_id = str(data['id'])
            payload['approval_id'] = approval_id
            try:
                co_ctx = parse_agent_regional_company_id(payload.get('company_id'))
            except ValueError:
                return APPROVAL_LOOKUP_UNAVAILABLE
            _APPROVAL_ROUTE_CONTEXT[approval_id] = {
                'agent_id': str(payload.get('agent_id') or ''),
                'company_id': co_ctx,
                'service': str(payload.get('service') or 'hosting'),
                'action': str(payload.get('action') or ''),
                'arguments_hash': str(payload.get('arguments_hash') or ''),
            }
        return status or None
    except Exception as exc:  # noqa: BLE001
        logger.debug('MCP approval lookup unavailable: identity_request_failed')
        return APPROVAL_LOOKUP_UNAVAILABLE


def approval_state(payload: dict, *, use_mcp_approval_protocol: bool = True) -> str | None:
    """Return Identity approval status, or ``APPROVAL_LOOKUP_UNAVAILABLE`` when Identity did not return a definite state.

    When ``use_mcp_approval_protocol`` is true (JSON-RPC MCP ``tools/call``), an unavailable lookup is not folded into
    ``pending`` so the caller avoids creating a duplicate approval in the same request.
    """
    status = lookup_approval_state(payload)
    if status == APPROVAL_LOOKUP_UNAVAILABLE:
        return APPROVAL_LOOKUP_UNAVAILABLE if use_mcp_approval_protocol else 'pending'
    if status in {'executed', 'approved', 'pending'}:
        return status
    return None


def consume_approval(approval_id: str, route_payload: dict | None = None) -> bool:
    base = _identity_base()
    if not base or not approval_id:
        return False
    claims = current_mcp_agent_claims()
    if mcp_personal_agent_rejected(claims):
        return False
    if not delegated_live_authority_ok(claims):
        return False
    ctx = _APPROVAL_ROUTE_CONTEXT.pop(str(approval_id), None)
    source = route_payload if isinstance(route_payload, dict) else ctx
    if not source:
        return False
    args_hash = str(source.get('arguments_hash') or '')
    if not args_hash and ctx:
        args_hash = str(ctx.get('arguments_hash') or '')
    raw_co = source.get('company_id')
    if raw_co is None and ctx:
        raw_co = ctx.get('company_id')
    try:
        co_int = parse_agent_regional_company_id(raw_co)
    except (TypeError, ValueError):
        return False
    payload = {
        'agent_id': str(source.get('agent_id') or (ctx or {}).get('agent_id') or ''),
        'company_id': co_int,
        'service': str(source.get('service') or (ctx or {}).get('service') or 'hosting'),
        'action': str(source.get('action') or (ctx or {}).get('action') or ''),
        'arguments_hash': args_hash,
    }
    assertion = _approval_route_assertion(payload)
    if not assertion:
        return False
    url = f'{base}/api/v1/mcp/internal/mcp-approval-consume'
    try:
        response = requests.post(
            url,
            json={'approval_id': str(approval_id)},
            headers={'Authorization': f'Bearer {assertion}'},
            timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10),
        )
        if response.status_code < 200 or response.status_code > 299:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        return body.get('consumed') is True
    except Exception as exc:  # noqa: BLE001
        logger.debug('MCP approval consume unavailable: identity_request_failed')
        return False


def forward_call_log(entry: dict) -> None:
    base = _identity_base()
    if not base:
        return
    try:
        assertion = build_mcp_call_log_assertion(audience_url=_identity_origin(), **signing_kwargs())
    except InternalAssertionError:
        logger.warning('MCP call log assertion rejected: mcp_assertion_rule')
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP call log assertion failed: mcp_assertion_error')
        return
    url = f'{base}/api/v1/mcp/internal/mcp-call-logs'
    body = build_identity_call_log_body(entry if isinstance(entry, dict) else {})
    if not body:
        logger.warning('MCP call log skipped: audit_fields_incomplete')
        return
    try:
        response = requests.post(
            url,
            json=body,
            headers={'Authorization': f'Bearer {assertion}'},
            timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10),
        )
        if response.status_code >= 400:
            logger.warning('MCP call log forward failed: HTTP %s', response.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP call log forward error: identity_request_failed')


def _revocation_verify_kwargs(origin: str) -> dict[str, Any]:
    """Verify with the pinned JWKS, else IDENTITY_JWKS_URL, never a URL guessed from the public issuer."""
    kwargs: dict[str, Any] = {'expected_issuer': origin}
    document = getattr(settings, 'IDENTITY_JWKS_DOCUMENT', None)
    if document is not None:
        kwargs['jwks'] = document
    else:
        jwks_url = getattr(settings, 'IDENTITY_JWKS_URL', None)
        if jwks_url:
            kwargs['identity_jwks_url'] = jwks_url
    return kwargs


def fetch_revocation_payload(*, company_id: int | None = None) -> dict | None:
    base = _identity_base()
    origin = _identity_origin()
    if not base or not origin:
        return None
    url = f'{base}/api/v1/mcp/internal/mcp-revocations'
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    if company_id is not None:
        try:
            params['company_id'] = str(parse_agent_regional_company_id(company_id))
        except ValueError:
            bump_delegated_authority_cache_on_identity_failure()
            return None
    try:
        headers['Authorization'] = f'Bearer {build_mcp_revocation_assertion(audience_url=origin, **signing_kwargs())}'
    except InternalAssertionError:
        logger.warning('MCP revocation assertion rejected: mcp_assertion_rule')
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP revocation assertion failed: mcp_assertion_error')
        return None
    try:
        response = requests.get(url, headers=headers, params=params or None, timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10))
        response.raise_for_status()
        data = response.json()
        try:
            revoked_ids, cache_seconds, agents = parse_trusted_revocation_poll_response(
                data,
                **_revocation_verify_kwargs(origin),
            )
        except InternalAssertionError:
            logger.warning('MCP revocation list untrusted: revocation_list_untrusted')
            bump_delegated_authority_cache_on_identity_failure()
            return None
        if company_id is not None:
            try:
                expect_cid = parse_agent_regional_company_id(company_id)
            except ValueError:
                bump_delegated_authority_cache_on_identity_failure()
                return None
            for row in agents:
                if not isinstance(row, dict):
                    bump_delegated_authority_cache_on_identity_failure()
                    return None
                try:
                    row_company = parse_agent_regional_company_id(row.get('company_id'))
                except ValueError:
                    bump_delegated_authority_cache_on_identity_failure()
                    return None
                if row_company != expect_cid:
                    bump_delegated_authority_cache_on_identity_failure()
                    return None
        return {
            'revoked_agent_ids': sorted(revoked_ids),
            'agents': agents,
            'cache_seconds': cache_seconds,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP revocation poll failed: identity_request_failed')
        bump_delegated_authority_cache_on_identity_failure()
        return None
