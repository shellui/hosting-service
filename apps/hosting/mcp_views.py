"""Hosting-service ``POST /mcp`` Streamable HTTP endpoint."""

from __future__ import annotations

import threading

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.generators import SchemaGenerator
from apps.hosting.mcp_identity import (
    approval_state,
    consume_approval,
    create_approval_request,
)
from apps.hosting.mcp_resource import hosting_mcp_resource_url
from apps.hosting.mcp_revocation import agent_revocation_denied
from apps.hosting.mcp_server import HostingMcpServer

_server: HostingMcpServer | None = None
_schema_cache: dict | None = None
_schema_lock = threading.Lock()


def _schema() -> dict:
    """Cached OpenAPI for MCP. Concurrent ``SchemaGenerator`` is not thread-safe."""
    global _schema_cache
    cached = _schema_cache
    if cached is not None:
        return cached
    with _schema_lock:
        if _schema_cache is not None:
            return _schema_cache
        _schema_cache = SchemaGenerator().get_schema(request=None, public=True)
        return _schema_cache


def _get_server() -> HostingMcpServer:
    global _server
    if _server is None:
        _server = HostingMcpServer(
            schema_provider=_schema,
            urlconf=settings.ROOT_URLCONF,
            service_name='hosting',
            identity_revocation_check=agent_revocation_denied,
            approval_handler=create_approval_request,
            approval_state=approval_state,
            approval_consume=consume_approval,
        )
    return _server


@csrf_exempt
def mcp_endpoint(request: HttpRequest):
    """POST /mcp. The server verifies the bearer token. Caller claims are not trusted."""
    return _get_server().handle(request)


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
