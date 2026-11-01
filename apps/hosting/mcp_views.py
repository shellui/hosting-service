"""Hosting-service ``POST /mcp`` Streamable HTTP endpoint."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.generators import SchemaGenerator
from rest_framework.request import Request
from shellui_mcp.server import McpServer

from apps.authapi.authentication import IdentityJWKSAuthentication
from apps.hosting.mcp_identity import (
    approval_state,
    consume_approval,
    create_approval_request,
    forward_call_log,
)
from apps.hosting.mcp_resource import audience_matches, hosting_mcp_resource_url
from apps.hosting.mcp_revocation import agent_revocation_denied

_server: McpServer | None = None


def _schema() -> dict:
    generator = SchemaGenerator()
    return generator.get_schema(request=None, public=True)


def _get_server() -> McpServer:
    global _server
    if _server is None:
        _server = McpServer(
            schema_provider=_schema,
            urlconf=settings.ROOT_URLCONF,
            service_name='hosting',
            identity_revocation_check=agent_revocation_denied,
            on_call=forward_call_log,
            approval_handler=create_approval_request,
            approval_state=approval_state,
            approval_consume=consume_approval,
        )
    return _server


def _staff_refused_for_mcp(principal, claims: dict) -> bool:
    if getattr(principal, 'is_staff', False):
        return True
    user_metadata = claims.get('user_metadata') or {}
    if isinstance(user_metadata, dict) and user_metadata.get('is_staff'):
        return True
    if claims.get('is_staff'):
        return True
    return False


def _agent_claims(request: HttpRequest) -> dict | None:
    auth = IdentityJWKSAuthentication()
    drf_request = Request(request)
    try:
        result = auth.authenticate(drf_request)
    except Exception:
        return None
    if not result:
        return None
    principal, _raw = result
    claims = dict(getattr(principal, 'claims', {}) or {})
    if not claims.get('agent_id'):
        return None
    if _staff_refused_for_mcp(principal, claims):
        return None
    if not audience_matches(claims, request):
        return None
    request.user = principal
    request.auth = claims
    return claims


@csrf_exempt
def mcp_endpoint(request: HttpRequest):
    claims = _agent_claims(request)
    return _get_server().handle(request, agent_claims=claims)


def oauth_protected_resource_metadata(request: HttpRequest):
    hosting_base = request.build_absolute_uri('/').rstrip('/')
    identity = (
        getattr(settings, 'IDENTITY_ISSUER', None) or getattr(settings, 'IDENTITY_SERVICE_URL', None) or ''
    ).rstrip('/')
    resource = hosting_mcp_resource_url(request)
    payload = {
        'resource': resource or f'{hosting_base}/mcp',
        'authorization_servers': [identity] if identity else [],
        'bearer_methods_supported': ['header'],
    }
    return JsonResponse(payload)
