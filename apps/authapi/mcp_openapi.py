"""OpenAPI ``x-mcp`` markers for Shellui MCP."""

from __future__ import annotations

from typing import Any

MCP_EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    '/api/v1/internal/',
    '/api/v1/scheduled-jobs',
)

MCP_FORBIDDEN_OPERATION_IDS: frozenset[str] = frozenset(
    {
        'hosting_v1_health_retrieve',
        'hosting_v1_access_retrieve',
        'hosting_v1_access_create',
        'hosting_v1_metrics_retrieve',
        'hosting_v1_metrics_all_retrieve',
        'hosting_v1_apps_deployments_upload_update',
        'api_v1_internal_company_deletions_create',
        'api_v1_scheduled_jobs_list',
        'api_v1_scheduled_jobs_runs_list',
        'api_v1_scheduled_jobs_runs_retrieve',
    }
)

MCP_REQUIRED_OPERATION_IDS: frozenset[str] = frozenset(
    {
        'hosting_v1_access_request_create',
        'hosting_v1_preview_create',
        'hosting_v1_apps_list',
        'hosting_v1_apps_create',
        'hosting_v1_apps_retrieve',
        'hosting_v1_apps_destroy',
        'hosting_v1_apps_renew_expiry_create',
        'hosting_v1_apps_deployments_list',
        'hosting_v1_apps_deployments_create',
        'hosting_v1_apps_deployments_artifact_upload_url_create',
        'hosting_v1_apps_deployments_artifact_upload_complete_create',
        'hosting_v1_apps_deployments_finalize_create',
        'hosting_v1_apps_deployments_rollback_create',
        'hosting_v1_deploy_tokens_retrieve',
        'hosting_v1_deploy_tokens_revoke_create',
        'hosting_v1_stats_retrieve',
        'api_v1_actions_events_list',
        'api_v1_actions_rules_list',
        'api_v1_actions_rules_create',
        'api_v1_actions_rules_retrieve',
        'api_v1_actions_rules_partial_update',
        'api_v1_actions_rules_destroy',
        'api_v1_actions_rules_rotate_secret',
        'api_v1_actions_rules_send_test',
        'api_v1_actions_deliveries_list',
        'api_v1_actions_deliveries_retrieve',
        'api_v1_actions_deliveries_requeue',
        'api_v1_actions_event_log_list',
        'api_v1_actions_event_log_retrieve',
        'api_v1_actions_event_log_types_list',
        'api_v1_actions_event_log_retention_retrieve',
        'hosting_v1_apps_domains_list',
        'hosting_v1_apps_domains_create',
        'hosting_v1_apps_domains_retrieve',
        'hosting_v1_apps_domains_destroy',
        'hosting_v1_apps_domains_refresh_create',
        'hosting_v1_apps_environment_list',
        'hosting_v1_apps_environment_create',
        'hosting_v1_apps_environment_retrieve',
        'hosting_v1_apps_environment_update',
        'hosting_v1_apps_environment_destroy',
        'hosting_v1_apps_runtime_logs_list',
        'hosting_v1_apps_request_logs_list',
    }
)

MCP_REQUIRED_SECRET_SCHEMA_PROPERTIES: frozenset[tuple[str, str]] = frozenset(
    {
        ('DeployTokenCreateResponse', 'token'),
        ('ActionRuleCreate', 'secret'),
        ('EnvVariableUpsert', 'value'),
        ('EnvVariableValue', 'value'),
    }
)

MCP_EXPLICIT_REGISTRY: dict[str, dict[str, Any]] = {}

# Public ``tools/list`` name for each OpenAPI ``operationId``.
# These are the names the ai-service gateway publishes (``hosting_<verb>_<noun>``).
# ``x-mcp.tool_name`` is the service-local verb_noun. The gateway prefixes ``hosting_``.
# shellui-django 0.5.1 names tools from ``operationId`` only, so ``HostingMcpServer`` applies this map.
MCP_GATEWAY_TOOL_NAMES: dict[str, str] = {
    'api_v1_actions_deliveries_list': 'hosting_list_action_deliveries',
    'api_v1_actions_deliveries_requeue': 'hosting_requeue_action_deliveries',
    'api_v1_actions_deliveries_retrieve': 'hosting_get_action_deliveries',
    'api_v1_actions_event_log_list': 'hosting_list_action_event_log',
    'api_v1_actions_event_log_retention_retrieve': 'hosting_get_action_event_log_retention',
    'api_v1_actions_event_log_retrieve': 'hosting_get_action_event_log',
    'api_v1_actions_event_log_types_list': 'hosting_list_action_event_log_types',
    'api_v1_actions_events_list': 'hosting_list_action_events',
    'api_v1_actions_rules_create': 'hosting_create_action_rules',
    'api_v1_actions_rules_destroy': 'hosting_delete_action_rules',
    'api_v1_actions_rules_list': 'hosting_list_action_rules',
    'api_v1_actions_rules_partial_update': 'hosting_update_action_rules',
    'api_v1_actions_rules_retrieve': 'hosting_get_action_rules',
    'api_v1_actions_rules_rotate_secret': 'hosting_rotate_rule_secret',
    'api_v1_actions_rules_send_test': 'hosting_send_test_rule',
    'hosting_v1_access_request_create': 'hosting_create_access_request',
    'hosting_v1_apps_create': 'hosting_create_apps',
    'hosting_v1_apps_deployments_artifact_upload_complete_create': (
        'hosting_create_apps_deployments_artifact_upload_complete'
    ),
    'hosting_v1_apps_deployments_artifact_upload_url_create': 'hosting_create_apps_deployments_artifact_upload_url',
    'hosting_v1_apps_deployments_create': 'hosting_create_apps_deployments',
    'hosting_v1_apps_deployments_finalize_create': 'hosting_create_apps_deployments_finalize',
    'hosting_v1_apps_deployments_list': 'hosting_list_apps_deployments',
    'hosting_v1_apps_deployments_rollback_create': 'hosting_create_apps_deployments_rollback',
    'hosting_v1_apps_destroy': 'hosting_delete_apps',
    'hosting_v1_apps_domains_create': 'hosting_create_apps_domains',
    'hosting_v1_apps_domains_destroy': 'hosting_delete_apps_domains',
    'hosting_v1_apps_domains_list': 'hosting_list_apps_domains',
    'hosting_v1_apps_domains_refresh_create': 'hosting_create_apps_domains_refresh',
    'hosting_v1_apps_domains_retrieve': 'hosting_get_apps_domains',
    'hosting_v1_apps_environment_create': 'hosting_create_apps_environment',
    'hosting_v1_apps_environment_destroy': 'hosting_delete_apps_environment',
    'hosting_v1_apps_environment_list': 'hosting_list_apps_environment',
    'hosting_v1_apps_environment_retrieve': 'hosting_get_apps_environment',
    'hosting_v1_apps_environment_update': 'hosting_replace_apps_environment',
    'hosting_v1_apps_list': 'hosting_list_apps',
    'hosting_v1_apps_renew_expiry_create': 'hosting_create_apps_renew_expiry',
    'hosting_v1_apps_request_logs_list': 'hosting_list_apps_request_logs',
    'hosting_v1_apps_retrieve': 'hosting_get_apps',
    'hosting_v1_apps_runtime_logs_list': 'hosting_list_apps_runtime_logs',
    'hosting_v1_deploy_tokens_retrieve': 'hosting_get_deploy_tokens',
    'hosting_v1_deploy_tokens_revoke_create': 'hosting_revoke_deploy_token',
    'hosting_v1_preview_create': 'hosting_create_preview',
    'hosting_v1_stats_retrieve': 'hosting_get_stats',
}


def gateway_local_tool_name(public_name: str) -> str:
    """Name stored on ``x-mcp.tool_name`` (no ``hosting_`` prefix; the gateway adds it)."""
    if not public_name.startswith('hosting_') or public_name.startswith('api_v1_'):
        raise ValueError(f'gateway tool name must be hosting_<verb>_<noun>: {public_name}')
    local = public_name[len('hosting_') :]
    if not local or local.startswith('hosting_') or local.startswith('api_v1_'):
        raise ValueError(f'gateway local tool name is invalid: {public_name}')
    return local


def public_name_for_operation(operation_id: str) -> str:
    try:
        return MCP_GATEWAY_TOOL_NAMES[operation_id]
    except KeyError as exc:
        raise KeyError(f'no gateway MCP name for {operation_id}') from exc


def operation_id_for_gateway_tool(name: str) -> str:
    for operation_id, public_name in MCP_GATEWAY_TOOL_NAMES.items():
        if public_name == name:
            return operation_id
    raise KeyError(name)


def _mcp_payload(*, read_only: bool, destructive: bool = False, sensitive: bool = False, tool_name: str) -> dict[str, Any]:
    return {
        'read_only': read_only,
        'destructive': destructive,
        'sensitive': sensitive,
        'tool_name': tool_name,
    }


def mcp_tool(
    *,
    operation_id: str,
    read_only: bool,
    destructive: bool = False,
    sensitive: bool = False,
) -> dict[str, Any]:
    """Register an MCP tool and return ``extend_schema`` kwargs (only explicit decoration exposes a tool)."""
    if operation_id in MCP_FORBIDDEN_OPERATION_IDS:
        raise ValueError(f'mcp_tool cannot tag forbidden operation: {operation_id}')
    payload = _mcp_payload(
        read_only=read_only,
        destructive=destructive,
        sensitive=sensitive,
        tool_name=gateway_local_tool_name(public_name_for_operation(operation_id)),
    )
    existing = MCP_EXPLICIT_REGISTRY.get(operation_id)
    if existing is not None and existing != payload:
        raise ValueError(f'mcp_tool called twice with different flags for {operation_id}')
    MCP_EXPLICIT_REGISTRY[operation_id] = payload
    return {'extensions': {'x-mcp': payload}}


def apply_gateway_mcp_names(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace shellui-django ``operationId`` tool names with the gateway public names."""
    renamed: list[dict[str, Any]] = []
    for tool in tools:
        meta = tool.get('_meta') if isinstance(tool.get('_meta'), dict) else {}
        operation_id = str(meta.get('operationId') or '')
        public = public_name_for_operation(operation_id)
        renamed.append({**tool, 'name': public})
    renamed.sort(key=lambda item: item['name'])
    return renamed


def mcp_extension(operation: dict[str, Any]) -> dict[str, Any] | None:
    raw = operation.get('x-mcp')
    if isinstance(raw, dict):
        return raw
    extensions = operation.get('extensions') or {}
    nested = extensions.get('x-mcp')
    return nested if isinstance(nested, dict) else None


def validate_mcp_schema(schema: dict[str, Any]) -> None:
    paths = schema.get('paths') or {}
    for prefix in MCP_EXCLUDED_PATH_PREFIXES:
        for path in paths:
            if path.startswith(prefix):
                raise AssertionError(f'excluded path must not appear in OpenAPI: {path}')

    tagged_in_schema: dict[str, dict[str, Any]] = {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for prefix in MCP_EXCLUDED_PATH_PREFIXES:
            if path.startswith(prefix):
                if any(mcp_extension(op) for op in path_item.values() if isinstance(op, dict)):
                    raise AssertionError(f'x-mcp must not appear under excluded path: {path}')
        for operation in path_item.values():
            if not isinstance(operation, dict) or 'operationId' not in operation:
                continue
            op_id = operation['operationId']
            ext = mcp_extension(operation)
            if op_id in MCP_FORBIDDEN_OPERATION_IDS and ext is not None:
                raise AssertionError(f'forbidden operation must not be tagged x-mcp: {op_id}')
            if ext is not None:
                tagged_in_schema[op_id] = ext

    if set(tagged_in_schema) != set(MCP_EXPLICIT_REGISTRY):
        raise AssertionError(
            f'x-mcp in schema must match mcp_tool registry only: '
            f'schema={sorted(tagged_in_schema)} registry={sorted(MCP_EXPLICIT_REGISTRY)}'
        )
    for op_id, payload in tagged_in_schema.items():
        if payload != MCP_EXPLICIT_REGISTRY[op_id]:
            raise AssertionError(f'x-mcp payload mismatch for {op_id}: {payload} != {MCP_EXPLICIT_REGISTRY[op_id]}')

    if set(MCP_GATEWAY_TOOL_NAMES) != MCP_REQUIRED_OPERATION_IDS:
        raise AssertionError(
            'gateway tool names must cover the MCP allowlist exactly: '
            f'missing={sorted(MCP_REQUIRED_OPERATION_IDS - set(MCP_GATEWAY_TOOL_NAMES))} '
            f'extra={sorted(set(MCP_GATEWAY_TOOL_NAMES) - MCP_REQUIRED_OPERATION_IDS)}'
        )
    public_names = list(MCP_GATEWAY_TOOL_NAMES.values())
    if len(public_names) != len(set(public_names)):
        raise AssertionError('duplicate gateway MCP tool names')
    for public_name in public_names:
        gateway_local_tool_name(public_name)

    missing_decorators = MCP_REQUIRED_OPERATION_IDS - set(MCP_EXPLICIT_REGISTRY)
    if missing_decorators:
        raise AssertionError(f'required operations missing mcp_tool decoration: {sorted(missing_decorators)}')

    extra_decorators = set(MCP_EXPLICIT_REGISTRY) - MCP_REQUIRED_OPERATION_IDS
    if extra_decorators:
        raise AssertionError(f'mcp_tool on operations outside allowlist: {sorted(extra_decorators)}')


def validate_mcp_secret_fields(schema: dict[str, Any]) -> None:
    components = schema.get('components') or {}
    schemas = components.get('schemas') or {}
    missing = []
    for component, prop in MCP_REQUIRED_SECRET_SCHEMA_PROPERTIES:
        definition = schemas.get(component) or {}
        props = definition.get('properties') or {}
        field = props.get(prop) or {}
        if field.get('x-mcp-secret') is not True:
            missing.append(f'{component}.{prop}')
    if missing:
        raise AssertionError(f'schema properties missing x-mcp-secret: {sorted(missing)}')
