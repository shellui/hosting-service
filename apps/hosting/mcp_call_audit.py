"""Safe MCP tool call audit fields for Identity call-log forwarding."""

from __future__ import annotations

from typing import Any, Final

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

# Static allowlist for ``error_code`` on failed outcomes (never free-form text).
ALL_CALL_LOG_ERROR_CODES: Final[frozenset[str]] = frozenset(
    set(ERROR_CODE_BY_STATUS.values())
    | {
        'invalid_status',
        'client_error',
        'server_error',
        'failed',
        'unexpected_status',
        'approval_pending',
        'approval_expired',
    }
)


def call_log_error_code_for_http(status_code: int | None) -> str:
    """Fixed allowlist for failed HTTP responses. Never returns None for status >= 400."""
    code = int(status_code or 0)
    if code < 400:
        return 'invalid_status'
    if code in ERROR_CODE_BY_STATUS:
        return ERROR_CODE_BY_STATUS[code]
    if 400 <= code <= 499:
        return 'client_error'
    if 500 <= code <= 599:
        return 'server_error'
    return 'failed'


def outcome_and_error_for_http(status_code: int | None) -> tuple[str, str | None]:
    """Map HTTP status to canonical outcome and ``error_code`` (None only when ``allowed``).

    Success is only explicit 2xx (`200` through `299`). Other codes never map to ``allowed``.
    """
    code = int(status_code or 0)
    if code < 100:
        return OUTCOME_FAILED, 'invalid_status'
    if 100 <= code <= 199:
        return OUTCOME_FAILED, 'unexpected_status'
    if 200 <= code <= 299:
        return OUTCOME_ALLOWED, None
    if 300 <= code <= 399:
        return OUTCOME_FAILED, 'unexpected_status'
    return OUTCOME_FAILED, call_log_error_code_for_http(code)


def call_log_access_kind(*, method: str, tool_read_only: bool) -> str:
    m = (method or 'GET').upper()
    if tool_read_only or m in READ_METHODS:
        return 'read'
    return 'write'


def operation_summary_or_id(schema: dict[str, Any], *, operation_id: str, path_template: str, method: str) -> str:
    """OpenAPI ``summary`` else ``operationId`` from this repo schema only (not client text)."""
    op = (schema.get('paths') or {}).get(path_template) or {}
    op_body = op.get((method or 'GET').lower()) or {}
    if not isinstance(op_body, dict):
        return operation_id[:500]
    oid = str(op_body.get('operationId') or '').strip()
    if oid and oid != operation_id:
        return operation_id[:500]
    summary = str(op_body.get('summary') or '').strip()
    if summary:
        return summary[:500]
    if oid:
        return oid[:500]
    return operation_id[:500]


def openapi_path_for_operation_id(schema: dict[str, Any], operation_id: str) -> str:
    """Path template from this repo OpenAPI by ``operationId`` (single source of truth)."""
    paths = schema.get('paths') or {}
    oid = (operation_id or '').strip()
    if not oid:
        return ''
    for path_key, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for http_m in ('get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace'):
            op = path_item.get(http_m)
            if not isinstance(op, dict):
                continue
            if str(op.get('operationId') or '').strip() == oid:
                return safe_path_template(str(path_key))
    return ''


def safe_path_template(path_template: str) -> str:
    """OpenAPI path template without query or fragment."""
    raw = str(path_template or '').strip()
    if not raw:
        return ''
    for sep in '?#':
        if sep in raw:
            raw = raw.split(sep, 1)[0]
    return raw[:2048]
