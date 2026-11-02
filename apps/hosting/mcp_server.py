"""Hosting-specific ``McpServer`` (tenant-safe tool calls)."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from shellui_django.mcp.server import McpServer


def _strip_agent_company_overrides(arguments: dict[str, Any]) -> dict[str, Any]:
    """Agents must not override tenant scope via tool ``query`` or ``body``."""
    cleaned = dict(arguments)
    query = dict(cleaned.get('query') or {})
    query.pop('company_id', None)
    cleaned['query'] = query
    body = cleaned.get('body')
    if isinstance(body, dict):
        body = dict(body)
        body.pop('company_id', None)
        cleaned['body'] = body
    return cleaned


class HostingMcpServer(McpServer):
    def _tools_call(
        self,
        request: HttpRequest,
        req_id: Any,
        params: dict[str, Any],
        agent_claims: dict[str, Any],
    ):
        arguments = params.get('arguments') or {}
        if agent_claims.get('agent_id'):
            params = dict(params)
            params['arguments'] = _strip_agent_company_overrides(arguments)
        return super()._tools_call(request, req_id, params, agent_claims)
