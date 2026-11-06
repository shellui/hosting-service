"""Safe MCP tool call audit fields for Identity call-log forwarding."""

from __future__ import annotations

from typing import Any

READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

# Canonical activity outcomes (Shellui shared contract).
OUTCOME_PENDING_APPROVAL = 'pending_approval'
OUTCOME_ALLOWED = 'allowed'
OUTCOME_DENIED = 'denied'
OUTCOME_FAILED = 'failed'
OUTCOME_SESSION_USED = 'session_used'

ERROR_CODE_BY_STATUS: dict[int, str] = {
    400: 'bad_request',
    401: 'unauthorized',
    403: 'forbidden',
    404: 'not_found',
    405: 'method_not_allowed',
    409: 'conflict',
    413: 'payload_too_large',
    422: 'unprocessable_entity',
    429: 'too_many_requests',
    500: 'internal_error',
    502: 'bad_gateway',
    503: 'service_unavailable',
    504: 'gateway_timeout',
}


def call_log_error_code_for_http(status_code: int | None) -> str | None:
    """Fixed allowlist for failed HTTP; None when unknown low status (never guess success)."""
    code = int(status_code or 0)
    if code < 400:
        return None
    if code in ERROR_CODE_BY_STATUS:
        return ERROR_CODE_BY_STATUS[code]
    if 400 <= code <= 499:
        return 'client_error'
    if 500 <= code <= 599:
        return 'server_error'
    return 'failed'


def outcome_and_error_for_http(status_code: int | None) -> tuple[str, str | None]:
    """Map HTTP status to canonical outcome and optional error_code."""
    code = int(status_code or 0)
    if code < 100:
        return OUTCOME_FAILED, 'invalid_status'
    if code < 400:
        return OUTCOME_ALLOWED, None
    return OUTCOME_FAILED, call_log_error_code_for_http(code)


def call_log_access_kind(*, method: str, tool_read_only: bool) -> str:
    m = (method or 'GET').upper()
    if tool_read_only or m in READ_METHODS:
        return 'read'
    return 'write'


def operation_summary_or_id(schema: dict[str, Any], *, tool_name: str, path_template: str, method: str) -> str:
    """OpenAPI ``summary`` else ``operationId`` from this repo schema only (not client text)."""
    op = (schema.get('paths') or {}).get(path_template) or {}
    op_body = op.get((method or 'GET').lower()) or {}
    if not isinstance(op_body, dict):
        return tool_name
    summary = str(op_body.get('summary') or '').strip()
    if summary:
        return summary[:500]
    oid = str(op_body.get('operationId') or '').strip()
    if oid:
        return oid[:500]
    return tool_name[:500]


def safe_path_template(path_template: str) -> str:
    """OpenAPI path template without query or fragment."""
    raw = str(path_template or '').strip()
    if not raw:
        return ''
    for sep in '?#':
        if sep in raw:
            raw = raw.split(sep, 1)[0]
    return raw[:2048]
