"""OpenAPI copy for company-owner admin APIs (written for agents and humans)."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse

from apps.authapi.mcp_openapi import MCP_REQUIRED_OPERATION_IDS
from apps.hosting.openapi_mcp_registry import MCP_SPECS
from apps.hosting.serializers import ErrorSerializer

PERMISSIONS_BLOCK = (
    'Permissions: Shellui company owner for the target company, or Shellui staff. '
    'Send `Authorization: Bearer <jwt>` from identity-service. '
    'Deploy tokens (`hdt_`) may call preview deploy, upload, and finalize routes for preview sites only. '
    'Shellui MCP agent tokens cannot create deploy tokens.'
)

COMPANY_QUERY = OpenApiParameter(
    name='company_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    required=False,
    description=(
        'Target company. Owners omit this when their JWT already carries `company_id`. '
        'Staff may set it to administer another company on Shellui Actions routes.'
    ),
)

APP_REF_PATH = OpenApiParameter(
    name='app_ref',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    description='Site slug (for example `my-app`) or app UUID.',
)

DEPLOYMENT_ID_PATH = OpenApiParameter(
    name='deployment_id',
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description='Deployment UUID from list or create responses.',
)

DOMAIN_ID_PATH = OpenApiParameter(
    name='domain_id',
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description='Custom domain UUID from list or create responses.',
)

ENV_KEY_PATH = OpenApiParameter(
    name='key',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    description='Environment variable name (letters, digits, underscore).',
)

TOKEN_ID_PATH = OpenApiParameter(
    name='token_id',
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description='Deploy token UUID from list or create responses.',
)

ACTION_RULE_ID_PATH = OpenApiParameter(
    name='id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.PATH,
    description='Shellui Actions webhook rule id.',
)

DELIVERY_ID_PATH = OpenApiParameter(
    name='delivery_id',
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description='Webhook delivery id (UUID string).',
)

EVENT_LOG_ID_PATH = OpenApiParameter(
    name='pk',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.PATH,
    description='Event log row id.',
)


def admin_description(
    *,
    lead: str,
    side_effects: str,
    sends_email: bool = False,
    destructive: bool = False,
    notes: str = '',
) -> str:
    """Standard MCP-facing operation description."""
    parts = [lead.strip(), PERMISSIONS_BLOCK]
    parts.append(f'Side effects: {side_effects.strip()}')
    parts.append(f'Sends email: {"Yes" if sends_email else "No"}.')
    parts.append(f'Destructive: {"Yes" if destructive else "No"}.')
    if notes.strip():
        parts.append(notes.strip())
    return '\n\n'.join(parts)


def _error_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(response=ErrorSerializer, description=description)


ADMIN_API_ERRORS = {
    400: _error_response(
        'Invalid query or body. Body uses `error` (stable machine code, for example `validation_failed`, '
        '`forbidden`) and `message`. Optional `field_errors` maps field names to stable tokens when validation fails.'
    ),
    401: _error_response('Missing or invalid Bearer token (`error`: `unauthorized`).'),
    403: _error_response(
        'Caller is authenticated but not allowed (`error`: `forbidden`). '
        'Common causes: hosting access not approved, wrong company, or agent token on a restricted route.'
    ),
    404: _error_response('Resource not found (`error`: for example `deployment_not_found`, `not_found`).'),
    409: _error_response('Conflict with current state (`error`: domain-specific stable code).'),
    429: _error_response(
        'Rate limited (`error`: `rate_limited`). Retry after backing off.'
    ),
}


def mcp_openapi_fields(operation_id: str) -> dict[str, str]:
    """Summary and description for an MCP allowlisted operation."""
    spec = MCP_SPECS.get(operation_id)
    if spec is None:
        raise KeyError(f'missing MCP OpenAPI registry entry for {operation_id}')
    return {
        'summary': spec.summary,
        'description': admin_description(
            lead=spec.lead,
            side_effects=spec.side_effects,
            sends_email=spec.sends_email,
            destructive=spec.destructive,
            notes=spec.notes,
        ),
    }


if set(MCP_SPECS) != MCP_REQUIRED_OPERATION_IDS:
    missing = MCP_REQUIRED_OPERATION_IDS - set(MCP_SPECS)
    extra = set(MCP_SPECS) - MCP_REQUIRED_OPERATION_IDS
    raise AssertionError(f'MCP_SPECS drift: missing={sorted(missing)} extra={sorted(extra)}')


EXAMPLE_APP = OpenApiExample(
    'Preview site',
    value={
        'id': '550e8400-e29b-41d4-a716-446655440000',
        'name': 'demo-preview',
        'slug': 'demo-preview',
        'company_id': 42,
        'display_name': 'Demo preview',
        'expires_at': '2026-11-08T12:00:00Z',
        'current_deployment_id': '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
        'urls': {'app': 'https://demo-preview.apps.example.test'},
        'created_at': '2026-11-01T12:00:00Z',
        'updated_at': '2026-11-01T12:00:00Z',
    },
)
