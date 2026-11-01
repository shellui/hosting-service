"""RFC 8707-style MCP resource metadata for hosting."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from shellui_mcp.resources import access_token_audience_matches, mcp_resource_from_origin


def hosting_mcp_resource_url(request: HttpRequest | None = None) -> str:
    """Canonical ``aud`` for agent tokens targeting this service's ``/mcp`` resource."""
    configured = (getattr(settings, 'HOSTING_MCP_RESOURCE', None) or '').strip().rstrip('/')
    if configured:
        return configured
    if request is not None:
        return request.build_absolute_uri('/mcp').rstrip('/')
    public = (getattr(settings, 'HOSTING_PUBLIC_URL', None) or '').strip().rstrip('/')
    if public:
        return mcp_resource_from_origin(public)
    return ''


def agent_token_audiences(request: HttpRequest | None = None) -> tuple[str, ...]:
    """Accepted ``aud`` values for MCP agent JWT decode (this service ``/mcp`` resource only)."""
    resource = hosting_mcp_resource_url(request)
    return (resource,) if resource else ()


def audience_matches(claims: dict, request: HttpRequest | None = None) -> bool:
    resource = hosting_mcp_resource_url(request)
    if not resource:
        return False
    return access_token_audience_matches(claims, resource)
