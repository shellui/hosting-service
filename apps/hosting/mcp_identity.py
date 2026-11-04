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
from shellui_django.mcp.masking import redact_mapping

from config.service_signing import signing_kwargs

logger = logging.getLogger(__name__)

APPROVAL_LOOKUP_UNAVAILABLE = '__approval_unavailable__'

_APPROVAL_ROUTE_CONTEXT: dict[str, dict[str, Any]] = {}


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
            logger.warning('MCP approval forward failed: %s %s', response.status_code, response.text[:200])
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
        return response.status_code < 400
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
                expected_issuer=origin,
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
