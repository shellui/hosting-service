"""Agent-facing MCP tool catalog.

``shellui-django`` 0.5.1 builds tool inputs as ``path``, ``method``, ``path_params``,
``query``, and ``body``. Agents were filling those transport fields and guessing
closed sets that the nested schema never listed. This module publishes the
catalog ``POST /mcp`` ``tools/list`` returns: flat arguments, enums, and
``readOnlyHint`` / ``destructiveHint`` annotations. Dispatch still uses the
OpenAPI path and method from tool metadata.
"""

from __future__ import annotations

from typing import Any

from shellui_django.mcp.openapi_tools import _body_schemas, _client_prop_schema, tools_from_schema
from shellui_django.mcp.routing import McpToolArgumentError

from apps.authapi.mcp_openapi import apply_gateway_mcp_names
from apps.hosting.openapi_mcp_registry import MCP_SPECS

# Callers must not supply these. Company scope comes from the JWT. The scheduled
# job run id is staff-only and is not an MCP argument.
HIDDEN_MCP_ARGUMENT_NAMES = frozenset({'company_id', 'scheduled_job_run_id'})

# Transport fields the library used to require. Ignored on input so a caller
# cannot retarget the tool. ``url`` is ignored only when it is not a real
# argument (Shellui Actions rules take a webhook ``url``).
TRANSPORT_ARGUMENT_NAMES = frozenset({'method', 'path', 'raw_url'})

_WRAPPER_ARGUMENT_NAMES = frozenset({'path_params', 'query', 'body'})


def _operation_by_id(schema: dict[str, Any], operation_id: str) -> dict[str, Any]:
    for path_item in (schema.get('paths') or {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if isinstance(operation, dict) and operation.get('operationId') == operation_id:
                return operation
    raise KeyError(operation_id)


def _parameter_properties(
    operation: dict[str, Any],
    root: dict[str, Any],
    *,
    location: str,
) -> tuple[dict[str, Any], list[str]]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in operation.get('parameters') or []:
        if not isinstance(param, dict) or param.get('in') != location:
            continue
        name = str(param.get('name') or '')
        if not name or name in HIDDEN_MCP_ARGUMENT_NAMES:
            continue
        properties[name] = _property_from_parameter(param, root)
        if param.get('required'):
            required.append(name)
    return properties, required


def _property_from_parameter(param: dict[str, Any], root: dict[str, Any], *, description: str = '') -> dict[str, Any]:
    raw = param.get('schema') if isinstance(param.get('schema'), dict) else {'type': 'string'}
    prop = _client_prop_schema(raw, root)
    text = description or str(param.get('description') or raw.get('description') or '').strip()
    if text and not prop.get('description'):
        prop['description'] = text
    return prop


def _path_properties(
    operation: dict[str, Any],
    root: dict[str, Any],
    path_names: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Arguments are the OpenAPI path template names, which dispatch substitutes.

    Spectacular renames ``{pk}`` to ``{id}`` and still emits the original ``pk``
    parameter. The tool takes ``id`` once, with the ``pk`` parameter's description.
    """
    by_name: dict[str, dict[str, Any]] = {}
    for param in operation.get('parameters') or []:
        if isinstance(param, dict) and param.get('in') == 'path' and param.get('name'):
            by_name[str(param['name'])] = param
    properties: dict[str, Any] = {}
    for name in path_names:
        param = by_name.get(name) or {'name': name, 'schema': {'type': 'string'}}
        description = ''
        if name == 'id' and not str(param.get('description') or '').strip():
            pk = by_name.get('pk') or {}
            pk_schema = pk.get('schema') if isinstance(pk.get('schema'), dict) else {}
            description = str(pk.get('description') or pk_schema.get('description') or '').strip()
        prop = _property_from_parameter(param, root, description=description)
        if not prop.get('description'):
            prop['description'] = name.replace('_', ' ') + '.'
        properties[name] = prop
    return properties, list(path_names)


def _flat_input_schema(
    operation: dict[str, Any],
    root: dict[str, Any],
    operation_id: str,
    path_names: list[str],
) -> dict[str, Any]:
    path_props, path_required = _path_properties(operation, root, path_names)
    query_props, query_required = _parameter_properties(operation, root, location='query')
    body_props, body_required = _body_schemas(operation, root)
    for hidden in HIDDEN_MCP_ARGUMENT_NAMES:
        body_props.pop(hidden, None)
    body_required = [name for name in body_required if name not in HIDDEN_MCP_ARGUMENT_NAMES]
    overlap = (
        (set(path_props) & set(query_props))
        | (set(path_props) & set(body_props))
        | (set(query_props) & set(body_props))
    )
    if overlap:
        raise ValueError(f'{operation_id} repeats argument names: {sorted(overlap)}')
    required: list[str] = []
    for name in [*path_required, *query_required, *body_required]:
        if name not in required:
            required.append(name)
    return {
        'additionalProperties': False,
        'properties': {**path_props, **query_props, **body_props},
        'required': required,
        'type': 'object',
    }


def published_mcp_tools(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Tools/list payload plus ``_meta`` for dispatch."""
    published: list[dict[str, Any]] = []
    for tool in apply_gateway_mcp_names(tools_from_schema(schema)):
        meta = tool.get('_meta') if isinstance(tool.get('_meta'), dict) else {}
        operation_id = str(meta.get('operationId') or '')
        spec = MCP_SPECS[operation_id]
        description = spec.agent.strip()
        if not description:
            raise ValueError(f'{operation_id} is missing an agent description')
        if '—' in description or '–' in description:
            raise ValueError(f'{operation_id} agent description uses a dash as punctuation')
        read_only = bool(meta.get('read_only'))
        destructive = bool(meta.get('destructive'))
        if read_only and destructive:
            raise ValueError(f'{operation_id} cannot be read-only and destructive')
        operation = _operation_by_id(schema, operation_id)
        path_names = [str(name) for name in (meta.get('path_params') or [])]
        published.append(
            {
                **tool,
                'annotations': {
                    'destructiveHint': destructive,
                    'readOnlyHint': read_only,
                },
                'description': description,
                'inputSchema': _flat_input_schema(operation, schema, operation_id, path_names),
            }
        )
    return published


def _clean_object(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise McpToolArgumentError(f'{label} must be an object.')
    return {str(key): item for key, item in value.items() if str(key) not in HIDDEN_MCP_ARGUMENT_NAMES}


def _names(meta: dict[str, Any], key: str) -> list[str]:
    raw = meta.get(key) or []
    return [str(name) for name in raw if str(name) not in HIDDEN_MCP_ARGUMENT_NAMES]


def normalize_mcp_arguments(arguments: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Map flat or legacy nested arguments onto ``path_params``, ``query``, and ``body``.

    ``method``, ``path``, and ``raw_url`` are ignored. The server dispatches with
    the tool's own OpenAPI method and path.
    """
    if not isinstance(arguments, dict):
        raise McpToolArgumentError('arguments must be an object.')
    path_names = _names(meta, 'path_params')
    query_names = _names(meta, 'query_fields')
    body_names = _names(meta, 'body_fields')
    declared = set(path_names) | set(query_names) | set(body_names)
    ignored = set(TRANSPORT_ARGUMENT_NAMES) | set(HIDDEN_MCP_ARGUMENT_NAMES)
    if 'url' not in declared:
        ignored.add('url')

    nested_path = _clean_object(arguments.get('path_params'), 'path_params')
    nested_query = _clean_object(arguments.get('query'), 'query')
    nested_body = _clean_object(arguments.get('body'), 'body')
    flat = {
        str(key): value
        for key, value in arguments.items()
        if str(key) not in _WRAPPER_ARGUMENT_NAMES and str(key) not in ignored
    }

    def take(names: list[str], nested: dict[str, Any]) -> dict[str, Any]:
        chosen: dict[str, Any] = {}
        for name in names:
            in_flat = name in flat
            in_nested = name in nested
            if in_flat and in_nested and flat[name] != nested[name]:
                raise McpToolArgumentError(f'{name} was provided twice with different values.')
            if in_flat:
                chosen[name] = flat.pop(name)
            elif in_nested:
                chosen[name] = nested[name]
        extra = sorted(set(nested) - set(names))
        if extra:
            raise McpToolArgumentError(f'Unexpected fields: {", ".join(extra)}.')
        return chosen

    path_params = take(path_names, nested_path)
    query = take(query_names, nested_query)
    body = take(body_names, nested_body)
    if flat:
        raise McpToolArgumentError(f'Unexpected arguments: {", ".join(sorted(flat))}.')
    return {'path_params': path_params, 'query': query, 'body': body}
