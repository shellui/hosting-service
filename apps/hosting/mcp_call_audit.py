"""Safe MCP tool call audit fields for Identity call-log forwarding (identity #135)."""

from __future__ import annotations

import time
from typing import Any

READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

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


def call_log_error_code(status_code: int | None) -> str:
    """Fixed allowlist error_code for Identity; avoids raw HTTP text."""
    code = int(status_code or 0)
    if code in ERROR_CODE_BY_STATUS:
        return ERROR_CODE_BY_STATUS[code]
    if 400 <= code <= 499:
        return 'client_error'
    if 500 <= code <= 599:
        return 'server_error'
    return 'ok'


def call_log_outcome(status_code: int | None) -> str:
    code = int(status_code or 0)
    if code < 200:
        return 'invalid'
    if code < 300:
        return 'success'
    if code < 400:
        return 'redirect'
    if code < 500:
        return 'client_error'
    return 'server_error'


def call_log_access_kind(*, method: str, tool_read_only: bool) -> str:
    m = (method or 'GET').upper()
    if tool_read_only or m in READ_METHODS:
        return 'read'
    return 'write'


def operation_title_from_schema(schema: dict[str, Any], *, tool_name: str, path_template: str, method: str) -> str:
    """Trusted OpenAPI summary or neutral operationId (internal schema only)."""
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


def safe_resource_path(path: str) -> str:
    """Strip query and fragment from resolved internal route path."""
    raw = str(path or '').strip()
    if not raw:
        return ''
    for sep in '?#':
        if sep in raw:
            raw = raw.split(sep, 1)[0]
    return raw[:2048]
