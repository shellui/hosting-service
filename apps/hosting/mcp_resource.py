"""RFC 8707-style MCP resource metadata for hosting."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from shellui_mcp.resources import access_token_audience_matches, mcp_resource_from_origin

_LEGACY_MCP_AUD = 'shellui-mcp'


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
    """Accepted ``aud`` values for MCP agent JWT decode (resource URL plus legacy fallback)."""
    values = [_LEGACY_MCP_AUD]
    resource = hosting_mcp_resource_url(request)
    if resource:
        values.append(resource)
    return tuple(dict.fromkeys(values))


def audience_matches(claims: dict, request: HttpRequest | None = None) -> bool:
    resource = hosting_mcp_resource_url(request)
    if resource and access_token_audience_matches(claims, resource):
        return True
    aud = claims.get('aud')
    if aud is None:
        return False
    if isinstance(aud, (list, tuple)):
        return _LEGACY_MCP_AUD in {str(item) for item in aud}
    return str(aud) == _LEGACY_MCP_AUD
