"""Build a strict-allowlist JSON body for Identity ``mcp-call-logs`` (no arbitrary tool arguments)."""

from __future__ import annotations

from typing import Any


def _nonempty_str(value: Any, *, max_len: int) -> str:
    s = str(value or '').strip()
    return s[:max_len]


def build_identity_call_log_body(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return body dict or None when required fields are missing."""
    agent_id = entry.get('agent_id')
    company_id = entry.get('company_id')
    if agent_id in (None, '') or company_id in (None, ''):
        return None
    try:
        company_int = int(company_id)
    except (TypeError, ValueError):
        return None
    tool = _nonempty_str(entry.get('tool'), max_len=200)
    resource_path = _nonempty_str(entry.get('resource_path'), max_len=2048)
    http_method = _nonempty_str(entry.get('http_method'), max_len=16).upper() or 'GET'
    operation_title = _nonempty_str(entry.get('operation_title'), max_len=500)
    access_kind = _nonempty_str(entry.get('access_kind'), max_len=32)
    outcome = _nonempty_str(entry.get('outcome'), max_len=32)
    error_code = _nonempty_str(entry.get('error_code'), max_len=64)
    if not all([tool, resource_path, operation_title, access_kind, outcome, error_code]):
        return None
    try:
        http_status = int(entry.get('http_status') or 0)
    except (TypeError, ValueError):
        http_status = 0
    try:
        duration_ms = int(entry.get('duration_ms') if entry.get('duration_ms') is not None else 0)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms < 0:
        duration_ms = 0
    request_id = _nonempty_str(entry.get('request_id'), max_len=128)

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
        'error_code': error_code,
        'duration_ms': duration_ms,
    }
    if request_id:
        body['request_id'] = request_id
    mcp_jsonrpc_id = entry.get('mcp_jsonrpc_id')
    if mcp_jsonrpc_id is not None and isinstance(mcp_jsonrpc_id, (str, int, float, bool)):
        body['mcp_jsonrpc_id'] = mcp_jsonrpc_id
    return body
