"""RFC 8707-style MCP resource metadata for hosting."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def hosting_mcp_resource_url(request: HttpRequest | None = None) -> str:
    """Canonical ``aud`` for agent tokens targeting this service's ``/mcp`` resource."""
    configured = (getattr(settings, 'HOSTING_MCP_RESOURCE', None) or '').strip().rstrip('/')
    if configured:
        return configured
    if request is not None:
        return request.build_absolute_uri('/mcp').rstrip('/')
    public = (getattr(settings, 'HOSTING_PUBLIC_URL', None) or '').strip().rstrip('/')
    if public:
        return f'{public}/mcp'
    return ''


def agent_token_audiences(request: HttpRequest | None = None) -> tuple[str, ...]:
    """Accepted ``aud`` values for MCP agent JWTs (resource URL plus legacy fallback)."""
    values = ['shellui-mcp']
    resource = hosting_mcp_resource_url(request)
    if resource:
        values.append(resource)
    configured = getattr(settings, 'IDENTITY_AUDIENCE', None)
    if configured and configured not in values:
        values.append(configured)
    return tuple(dict.fromkeys(values))


def audience_matches(claims: dict, request: HttpRequest | None = None) -> bool:
    aud = claims.get('aud')
    allowed = set(agent_token_audiences(request))
    if aud is None:
        return False
    if isinstance(aud, (list, tuple)):
        return bool(allowed.intersection({str(item) for item in aud}))
    return str(aud) in allowed
