"""Forward MCP approvals and call logs to identity-service."""

from __future__ import annotations

import inspect
import logging
from typing import Any
from uuid import UUID

import requests
from django.conf import settings

from shellui_django.mcp.internal import (
    InternalAssertionError,
    build_mcp_approval_assertion,
    build_mcp_call_log_assertion,
    build_mcp_revocation_assertion,
    parse_trusted_revocation_poll_response,
)
from shellui_django.mcp.masking import redact_mapping

from apps.hosting.mcp_context import current_mcp_agent_claims
from config.service_signing import signing_kwargs

logger = logging.getLogger(__name__)

APPROVAL_LOOKUP_UNAVAILABLE = '__approval_unavailable__'

_APPROVAL_ROUTE_CONTEXT: dict[str, dict[str, Any]] = {}

_APPROVAL_ASSERTION_KWARG_NAMES: frozenset[str] | None = None


def _approval_assertion_extra_kwargs() -> dict[str, Any]:
    """Forward optional identity-bound fields from the live agent JWT into approval assertions.

    shellui-django may add parameters (for example ``global_company_id``, ``grant_version``, ``agent_binding``)
    after django-commons#14; only pass keys the installed library accepts.
    """
    global _APPROVAL_ASSERTION_KWARG_NAMES
    if _APPROVAL_ASSERTION_KWARG_NAMES is None:
        try:
            params = inspect.signature(build_mcp_approval_assertion).parameters
        except (TypeError, ValueError):
            _APPROVAL_ASSERTION_KWARG_NAMES = frozenset()
        else:
            reserved = frozenset(
                {
                    'company_id',
                    'agent_id',
                    'service',
                    'action',
                    'arguments_hash',
                    'audience_url',
                    'lifetime_seconds',
                    'private_key_pem',
                    'kid',
                    'issuer',
                }
            )
            _APPROVAL_ASSERTION_KWARG_NAMES = frozenset(p for p in params if p not in reserved)

    if not _APPROVAL_ASSERTION_KWARG_NAMES:
        return {}

    claims = current_mcp_agent_claims() or {}
    if not isinstance(claims, dict):
        return {}

    out: dict[str, Any] = {}
    if 'global_company_id' in _APPROVAL_ASSERTION_KWARG_NAMES:
        raw = claims.get('global_company_id')
        if raw not in (None, ''):
            gid = str(raw).strip()
            try:
                out['global_company_id'] = str(UUID(gid))
            except ValueError:
                logger.warning('Agent JWT global_company_id is not a valid UUID; omitting from MCP approval assertion.')

    if 'grant_version' in _APPROVAL_ASSERTION_KWARG_NAMES and claims.get('grant_version') is not None:
        try:
            out['grant_version'] = int(claims['grant_version'])
        except (TypeError, ValueError):
            logger.warning('Agent JWT grant_version is not an integer; omitting from MCP approval assertion.')

    if 'agent_binding' in _APPROVAL_ASSERTION_KWARG_NAMES and claims.get('agent_binding') not in (None, ''):
        out['agent_binding'] = str(claims['agent_binding'])

    return out


def _identity_origin() -> str:
    return (getattr(settings, 'IDENTITY_ISSUER', None) or getattr(settings, 'IDENTITY_SERVICE_URL', None) or '').rstrip('/')


def _identity_base() -> str:
    return (getattr(settings, 'IDENTITY_SERVICE_URL', None) or _identity_origin()).rstrip('/')


def create_approval_request(payload: dict) -> dict | None:
    base = _identity_base()
    if not base:
        return None
    agent_id = str(payload.get('agent_id') or '')
    company_id = payload.get('company_id')
    if not agent_id or company_id is None:
        return None
    try:
        assertion = build_mcp_approval_assertion(
            company_id=int(company_id),
            agent_id=agent_id,
            service=str(payload.get('service') or 'hosting'),
            action=str(payload.get('action') or ''),
            arguments_hash=str(payload.get('arguments_hash') or ''),
            audience_url=_identity_origin(),
            **_approval_assertion_extra_kwargs(),
            **signing_kwargs(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP approval assertion failed: %s', exc)
        return None
    url = f'{base}/api/v1/mcp/internal/mcp-approval-requests'
    body = {
        'arguments': redact_mapping(payload.get('arguments') or {}, read_sensitive=False),
    }
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
        logger.warning('MCP approval forward error: %s', exc)
        return None


def _approval_route_assertion(payload: dict) -> str | None:
    agent_id = str(payload.get('agent_id') or '')
    company_id = payload.get('company_id')
    args_hash = str(payload.get('arguments_hash') or '')
    if not agent_id or company_id is None or not args_hash:
        return None
    try:
        return build_mcp_approval_assertion(
            company_id=int(company_id),
            agent_id=agent_id,
            service=str(payload.get('service') or 'hosting'),
            action=str(payload.get('action') or ''),
            arguments_hash=args_hash,
            audience_url=_identity_origin(),
            **_approval_assertion_extra_kwargs(),
            **signing_kwargs(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP approval assertion failed: %s', exc)
        return None


def lookup_approval_state(payload: dict) -> str | None:
    """Return ``pending``, ``approved``, ``executed``, or None by asking identity-service."""
    base = _identity_base()
    if not base:
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
            _APPROVAL_ROUTE_CONTEXT[approval_id] = {
                'agent_id': str(payload.get('agent_id') or ''),
                'company_id': int(payload.get('company_id')),
                'service': str(payload.get('service') or 'hosting'),
                'action': str(payload.get('action') or ''),
                'arguments_hash': str(payload.get('arguments_hash') or ''),
            }
        return status or None
    except Exception as exc:  # noqa: BLE001
        logger.debug('MCP approval lookup unavailable: %s', exc)
        return APPROVAL_LOOKUP_UNAVAILABLE


def approval_state(payload: dict) -> str | None:
    status = lookup_approval_state(payload)
    if status == APPROVAL_LOOKUP_UNAVAILABLE:
        return 'pending'
    if status in {'executed', 'approved', 'pending'}:
        return status
    return None


def consume_approval(approval_id: str, route_payload: dict | None = None) -> bool:
    base = _identity_base()
    if not base or not approval_id:
        return False
    ctx = _APPROVAL_ROUTE_CONTEXT.pop(str(approval_id), None)
    source = route_payload if isinstance(route_payload, dict) else ctx
    if not source:
        return False
    args_hash = str(source.get('arguments_hash') or '')
    if not args_hash and ctx:
        args_hash = str(ctx.get('arguments_hash') or '')
    payload = {
        'agent_id': str(source.get('agent_id') or (ctx or {}).get('agent_id') or ''),
        'company_id': source.get('company_id') if source.get('company_id') is not None else (ctx or {}).get('company_id'),
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
        logger.debug('MCP approval consume unavailable: %s', exc)
        return False


def forward_call_log(entry: dict) -> None:
    base = _identity_base()
    if not base:
        return
    try:
        assertion = build_mcp_call_log_assertion(audience_url=_identity_origin(), **signing_kwargs())
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP call log assertion failed: %s', exc)
        return
    url = f'{base}/api/v1/mcp/internal/mcp-call-logs'
    body = {
        'agent_id': entry.get('agent_id'),
        'company_id': entry.get('company_id'),
        'service': entry.get('service') or 'hosting',
        'tool': entry.get('tool') or '',
        'method': entry.get('method') or '',
        'path': entry.get('path') or '',
        'status': entry.get('status') or 0,
        'arguments': entry.get('arguments') or {},
    }
    try:
        requests.post(
            url,
            json=body,
            headers={'Authorization': f'Bearer {assertion}'},
            timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP call log forward error: %s', exc)


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
        params['company_id'] = str(int(company_id))
    try:
        headers['Authorization'] = f'Bearer {build_mcp_revocation_assertion(audience_url=origin, **signing_kwargs())}'
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP revocation assertion failed: %s', exc)
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
        except InternalAssertionError as exc:
            logger.warning('MCP revocation list untrusted: %s', exc.message)
            return None
        if company_id is not None:
            for row in agents:
                if not isinstance(row, dict):
                    return None
                try:
                    row_company = int(row.get('company_id'))
                except (TypeError, ValueError):
                    return None
                if row_company != int(company_id):
                    return None
        return {
            'revoked_agent_ids': sorted(revoked_ids),
            'agents': agents,
            'cache_seconds': cache_seconds,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP revocation poll failed: %s', exc)
        return None
