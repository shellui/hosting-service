"""Forward MCP approvals and call logs to identity-service."""

from __future__ import annotations

import logging
from typing import Any

import jwt
import requests
from django.conf import settings

import shellui_mcp.internal as mcp_internal
from shellui_mcp.internal import (
    InternalAssertionError,
    REVOCATION_AUDIENCE,
    REVOCATION_SCOPE,
    build_mcp_approval_assertion,
    build_mcp_call_log_assertion,
    build_mcp_revocation_assertion,
)
from shellui_mcp.masking import redact_mapping

from apps.authapi.jwks_client import get_jwks_client

logger = logging.getLogger(__name__)

APPROVAL_LOOKUP_UNAVAILABLE = '__approval_unavailable__'


def _identity_origin() -> str:
    return (getattr(settings, 'IDENTITY_ISSUER', None) or getattr(settings, 'IDENTITY_SERVICE_URL', None) or '').rstrip('/')


def _identity_base() -> str:
    return (getattr(settings, 'IDENTITY_SERVICE_URL', None) or _identity_origin()).rstrip('/')


def _verify_identity_signed_assertion(raw: str, *, expected_audience: str, expected_scope: str) -> bool:
    if not raw or not raw.strip():
        return False
    token = raw.strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    options = {
        'require': ['exp', 'iat', 'aud', 'scope'],
        'verify_aud': True,
        'verify_iss': bool(settings.IDENTITY_ISSUER),
    }
    kwargs: dict[str, Any] = {'audience': expected_audience, 'options': options}
    if settings.IDENTITY_ISSUER:
        kwargs['issuer'] = settings.IDENTITY_ISSUER
    try:
        key = get_jwks_client().get_signing_key(token)
        if key is not None:
            claims = jwt.decode(token, key=key.key, algorithms=['RS256'], **kwargs)
        else:
            secret = getattr(settings, 'JWT_HS256_FALLBACK_SECRET', None)
            if not (secret and (settings.DEBUG or getattr(settings, 'ALLOW_JWT_HS256_FALLBACK', False))):
                return False
            claims = jwt.decode(token, key=secret, algorithms=['HS256'], **kwargs)
        return str(claims.get('scope') or '') == expected_scope
    except (jwt.InvalidTokenError, InternalAssertionError):
        return False


def _revocation_list_trusted(data: dict) -> bool:
    assertion = data.get('assertion') or data.get('revocation_assertion')
    if not assertion:
        return True
    return _verify_identity_signed_assertion(
        str(assertion), expected_audience=REVOCATION_AUDIENCE, expected_scope=REVOCATION_SCOPE
    )


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


def lookup_approval_state(payload: dict) -> str | None:
    """Return ``pending``, ``approved``, ``executed``, or None by asking identity-service."""
    base = _identity_base()
    if not base:
        return None
    agent_id = str(payload.get('agent_id') or '')
    company_id = payload.get('company_id')
    args_hash = str(payload.get('arguments_hash') or '')
    if not agent_id or company_id is None or not args_hash:
        return None
    try:
        assertion = build_mcp_approval_assertion(
            company_id=int(company_id),
            agent_id=agent_id,
            service=str(payload.get('service') or 'hosting'),
            action=str(payload.get('action') or ''),
            arguments_hash=args_hash,
            audience_url=_identity_origin(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP approval lookup assertion failed: %s', exc)
        return None
    url = f'{base}/api/v1/mcp/internal/mcp-approval-state'
    params = {
        'agent_id': agent_id,
        'company_id': company_id,
        'service': str(payload.get('service') or 'hosting'),
        'action': str(payload.get('action') or ''),
        'arguments_hash': args_hash,
    }
    try:
        response = requests.get(
            url,
            params=params,
            headers={'Authorization': f'Bearer {assertion}'},
            timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10),
        )
        if response.status_code == 404 or response.status_code >= 400:
            return APPROVAL_LOOKUP_UNAVAILABLE
        data = response.json()
        status = str(data.get('status') or '')
        if status == 'approved' and data.get('id'):
            payload['approval_id'] = str(data['id'])
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


def consume_approval(approval_id: str) -> bool:
    base = _identity_base()
    if not base or not approval_id:
        return False
    builder = getattr(mcp_internal, 'build_mcp_approval_consume_assertion', None)
    if builder is None:
        try:
            assertion = build_mcp_call_log_assertion(audience_url=_identity_origin())
        except Exception:  # noqa: BLE001
            return False
    else:
        try:
            assertion = builder(audience_url=_identity_origin(), approval_id=approval_id)
        except Exception:  # noqa: BLE001
            return False
    url = f'{base}/api/v1/mcp/internal/mcp-approval-consume/{approval_id}'
    try:
        response = requests.post(
            url,
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
        assertion = build_mcp_call_log_assertion(audience_url=_identity_origin())
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


def fetch_revocation_payload() -> dict | None:
    base = _identity_base()
    if not base:
        return None
    url = f'{base}/api/v1/mcp/internal/mcp-revocations'
    headers: dict[str, str] = {}
    try:
        headers['Authorization'] = f'Bearer {build_mcp_revocation_assertion(audience_url=_identity_origin())}'
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP revocation assertion failed: %s', exc)
        return None
    try:
        response = requests.get(url, headers=headers, timeout=getattr(settings, 'IDENTITY_SYNC_TIMEOUT', 10))
        response.raise_for_status()
        data = response.json()
        if not _revocation_list_trusted(data):
            logger.warning('MCP revocation list signature rejected')
            return None
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning('MCP revocation poll failed: %s', exc)
        return None
