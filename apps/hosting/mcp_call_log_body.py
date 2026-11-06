"""Build a strict-allowlist JSON body for Identity ``mcp-call-logs`` (no arbitrary tool arguments or client text)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.authapi.mcp_authority import parse_agent_regional_company_id, strict_non_negative_int_optional
from apps.hosting.mcp_call_audit import ALL_CALL_LOG_ERROR_CODES, OUTCOME_ALLOWED

# Canonical outcomes (Shellui shared contract); must match ``mcp_call_audit``.
CANONICAL_OUTCOMES = frozenset(
    {
        'pending_approval',
        OUTCOME_ALLOWED,
        'denied',
        'failed',
        'session_used',
    }
)


def _nonempty_str(value: Any, *, max_len: int) -> str:
    s = str(value or '').strip()
    return s[:max_len]


def _optional_uuid(value: Any) -> str | None:
    if value in (None, ''):
        return None
    try:
        return str(UUID(str(value).strip()))
    except ValueError:
        return None


def build_identity_call_log_body(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return body dict or None when required fields are missing.

    Excludes caller-provided correlation ids (no ``request_id``, no ``mcp_jsonrpc_id``).
    ``error_code`` is required for every outcome except ``allowed``; it must be a static enum value from
    ``ALL_CALL_LOG_ERROR_CODES``. Success (``allowed``) never carries ``error_code``.
    ``approval_request_id`` only when valid UUID.
    """
    agent_id = entry.get('agent_id')
    company_id = entry.get('company_id')
    if agent_id in (None, '') or company_id in (None, ''):
        return None
    try:
        company_int = parse_agent_regional_company_id(company_id)
    except ValueError:
        return None

    tool = _nonempty_str(entry.get('tool'), max_len=200)
    resource_path = _nonempty_str(entry.get('resource_path'), max_len=2048)
    http_method = _nonempty_str(entry.get('http_method'), max_len=16).upper() or 'GET'
    operation_title = _nonempty_str(entry.get('operation_title'), max_len=500)
    access_kind = _nonempty_str(entry.get('access_kind'), max_len=32)
    outcome = _nonempty_str(entry.get('outcome'), max_len=32)
    if not all([tool, resource_path, operation_title, access_kind, outcome]):
        return None
    if outcome not in CANONICAL_OUTCOMES:
        return None

    error_raw = entry.get('error_code')
    if outcome == OUTCOME_ALLOWED:
        if error_raw not in (None, ''):
            return None
        error_code = None
    else:
        error_code = _nonempty_str(error_raw, max_len=64)
        if not error_code or error_code not in ALL_CALL_LOG_ERROR_CODES:
            return None

    try:
        http_status = int(entry.get('http_status') if entry.get('http_status') is not None else 0)
    except (TypeError, ValueError):
        http_status = 0
    if http_status < 0:
        http_status = 0

    try:
        duration_ms = int(entry.get('duration_ms') if entry.get('duration_ms') is not None else 0)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms < 0:
        duration_ms = 0

    body: dict[str, Any] = {
        'agent_id': str(agent_id),
        'company_id': company_int,
        'service': _nonempty_str(entry.get('service') or 'hosting', max_len=64) or 'hosting',
        'tool': tool,
        'operation_title': operation_title,
        'resource_path': resource_path,
        'http_method': http_method,
        'http_status': http_status,
        'access_kind': access_kind,
        'outcome': outcome,
        'duration_ms': duration_ms,
    }
    if error_code:
        body['error_code'] = error_code

    gv = entry.get('grant_version')
    if gv is not None and gv != '':
        try:
            gvi = strict_non_negative_int_optional(gv, field='grant_version')
        except ValueError:
            return None
        if gvi is not None:
            body['grant_version'] = gvi

    cbv = entry.get('company_binding_version')
    if cbv is not None and cbv != '':
        try:
            cbvi = strict_non_negative_int_optional(cbv, field='company_binding_version')
        except ValueError:
            return None
        if cbvi is not None:
            body['company_binding_version'] = cbvi

    gci = entry.get('global_company_id')
    if gci not in (None, ''):
        u = _optional_uuid(gci)
        if u is None:
            return None
        body['global_company_id'] = u

    appr_id = _optional_uuid(entry.get('approval_request_id'))
    if appr_id:
        body['approval_request_id'] = appr_id

    return body
