"""Put closed sets on the OpenAPI schemas the MCP catalog is built from.

Query and body fields that only accept a fixed set of ids were plain strings.
Agents guessed, and the call failed. This hook writes ``enum`` and a short
description onto the parameter or body schema spectacular publishes.
"""

from __future__ import annotations

from typing import Any

from apps.authapi.mcp_openapi import mcp_extension

DELIVERY_STATUS_VALUES = ('pending', 'delivered', 'failed', 'dead')

_STATUS_DESCRIPTION = 'Delivery status to include.'
_EVENT_QUERY_DESCRIPTION = 'Catalog event id to match.'
_EVENT_LOG_DESCRIPTION = 'One catalog event id to match.'
_EVENT_BODY_DESCRIPTION = 'Shellui Actions event id this rule subscribes to.'


def _webhook_event_ids() -> list[str]:
    from apps.actions.registry import webhook_event_types

    return [event.id for event in webhook_event_types()]


def _company_event_ids() -> list[str]:
    from apps.actions.registry import company_event_types

    return [event.id for event in company_event_types()]


def _deref(schema: Any, root: dict[str, Any], seen: set[str] | None = None) -> dict[str, Any] | None:
    if not isinstance(schema, dict):
        return None
    seen = seen or set()
    ref = schema.get('$ref')
    if isinstance(ref, str) and ref.startswith('#/'):
        if ref in seen:
            return None
        target: Any = root
        for part in ref.lstrip('#/').split('/'):
            if not isinstance(target, dict):
                return None
            target = target.get(part)
        if not isinstance(target, dict):
            return None
        return _deref(target, root, seen | {ref})
    return schema


def _schema_objects(schema: Any, root: dict[str, Any], seen: set[str] | None = None):
    seen = seen or set()
    node = _deref(schema, root, seen)
    if not isinstance(node, dict):
        return
    yield node
    for key in ('allOf', 'anyOf', 'oneOf'):
        parts = node.get(key)
        if isinstance(parts, list):
            for part in parts:
                yield from _schema_objects(part, root, seen)


def _apply_enum(prop: dict[str, Any], values: list[str], description: str) -> None:
    prop['type'] = 'string'
    prop['enum'] = list(values)
    if not str(prop.get('description') or '').strip():
        prop['description'] = description


def _query_enums(operation_id: str) -> dict[str, tuple[list[str], str]]:
    if operation_id == 'api_v1_actions_deliveries_list':
        return {
            'status': (list(DELIVERY_STATUS_VALUES), _STATUS_DESCRIPTION),
            'event_type': (_webhook_event_ids(), _EVENT_QUERY_DESCRIPTION),
        }
    if operation_id == 'api_v1_actions_event_log_list':
        return {'event_type': (_company_event_ids(), _EVENT_LOG_DESCRIPTION)}
    return {}


def _body_enums(operation_id: str) -> dict[str, tuple[list[str], str]]:
    if operation_id in {'api_v1_actions_rules_create', 'api_v1_actions_rules_partial_update'}:
        return {'event_type': (_webhook_event_ids(), _EVENT_BODY_DESCRIPTION)}
    return {}


def postprocess_mcp_enums(result, generator, request, public):
    """Attach enums to MCP operation parameters and JSON bodies."""
    del generator, request, public
    for path_item in (result.get('paths') or {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict) or mcp_extension(operation) is None:
                continue
            operation_id = str(operation.get('operationId') or '')
            query_enums = _query_enums(operation_id)
            for param in operation.get('parameters') or []:
                if not isinstance(param, dict):
                    continue
                schema = param.get('schema')
                if not isinstance(schema, dict):
                    schema = {'type': 'string'}
                    param['schema'] = schema
                description = str(param.get('description') or '').strip()
                if description and not str(schema.get('description') or '').strip():
                    schema['description'] = description
                spec = query_enums.get(str(param.get('name') or ''))
                if spec is None:
                    continue
                values, enum_description = spec
                _apply_enum(schema, values, enum_description)
                if not description:
                    param['description'] = schema['description']
            body_enums = _body_enums(operation_id)
            if not body_enums:
                continue
            request_body = operation.get('requestBody') or {}
            content = request_body.get('content') if isinstance(request_body, dict) else None
            json_schema = (content or {}).get('application/json', {}).get('schema') if isinstance(content, dict) else None
            for node in _schema_objects(json_schema, result):
                properties = node.get('properties')
                if not isinstance(properties, dict):
                    continue
                for name, (values, description) in body_enums.items():
                    prop = properties.get(name)
                    if isinstance(prop, dict):
                        _apply_enum(prop, values, description)
    return result
