"""Hosting-specific ``McpServer`` (tenant-safe tool args + Identity-safe call-log audit fields)."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpRequest, JsonResponse
from django.urls import Resolver404, resolve
from shellui_django.mcp.masking import redact_mapping
from shellui_django.mcp.openapi_mcp import marker_tree_for_operation_response
from shellui_django.mcp.openapi_tools import tools_from_schema
from shellui_django.mcp.rate_limit import check_agent_rate_limit
from shellui_django.mcp.routing import McpToolArgumentError, materialize_openapi_path, validate_mcp_tool_arguments
from shellui_django.mcp.server import McpServer
from shellui_django.mcp.write_gate import decide_write, is_destructive_operation

from apps.authapi.mcp_authority import (
    authority_context_for_call_log,
    is_exchange_delegated_regional_agent,
    mcp_personal_agent_rejected,
    strict_non_negative_int_optional,
)
from apps.hosting.mcp_call_audit import (
    OUTCOME_ALLOWED,
    OUTCOME_DENIED,
    OUTCOME_FAILED,
    OUTCOME_WAITING_APPROVAL,
    call_log_access_kind,
    openapi_path_for_operation_id,
    outcome_and_error_for_http,
)
from apps.hosting.mcp_identity import APPROVAL_LOOKUP_UNAVAILABLE
from apps.hosting.mcp_live_authority import (
    DELEGATED_AUTH_REASON_MISCONFIGURED,
    DELEGATED_AUTH_REASON_UNAVAILABLE,
    delegated_live_authority_state,
)

_BODYLESS_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})
_ARTIFACT_UPLOAD_URL_TOOL = 'hosting_v1_apps_deployments_artifact_upload_url_create'


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


def _dispatch_kwargs(method: str, arguments: dict[str, Any], authorization: str) -> dict[str, Any]:
    """Build the inner REST request.

    Tool bodies arrive as JSON objects. ``APIRequestFactory`` would otherwise send a dict as
    ``application/octet-stream``, and DRF then rejects every write that reads ``request.data``.
    """
    kwargs: dict[str, Any] = {
        'query_params': arguments.get('query') or {},
        'HTTP_AUTHORIZATION': authorization,
    }
    if method in _BODYLESS_METHODS:
        return kwargs
    body = arguments.get('body')
    if body is None:
        body = {}
    if isinstance(body, (dict, list)):
        kwargs['data'] = json.dumps(body)
        kwargs['content_type'] = 'application/json'
    else:
        kwargs['data'] = body
    return kwargs


def _public_tool_payload(
    data: Any,
    *,
    read_sensitive: bool,
    markers: dict[str, Any],
    tool_name: str,
) -> Any:
    """Redact a proxied REST payload without changing its JSON shape.

    OpenAPI list operations return arrays. Wrapping them in ``{"result": ...}`` makes the tool
    result disagree with the operation schema. Presigned S3 upload URLs stay masked. A direct
    hosting PUT URL is not a credential (the agent still sends its bearer token), so safe-read
    agents can follow the upload step.
    """
    if isinstance(data, list):
        return [
            redact_mapping(item, read_sensitive=read_sensitive, markers=markers)
            if isinstance(item, dict)
            else item
            for item in data
        ]
    if not isinstance(data, dict):
        return redact_mapping(None, read_sensitive=read_sensitive, markers=markers)
    redacted = redact_mapping(data, read_sensitive=read_sensitive, markers=markers)
    if (
        tool_name == _ARTIFACT_UPLOAD_URL_TOOL
        and data.get('backend') == 'direct'
        and data.get('upload_url')
    ):
        redacted['upload_url'] = data['upload_url']
    return redacted


class HostingMcpServer(McpServer):
    """Same tool dispatch as ``shellui_django.mcp.server.McpServer`` with safe call-log metadata."""

    def _forward_call_log(
        self,
        *,
        schema: dict[str, Any],
        agent_claims: dict[str, Any],
        tool_name: str,
        path_template: str,
        method: str,
        tool_read_only: bool,
        destructive: bool,
        duration_ms: int,
        http_status: int,
        outcome: str,
        error_code: str | None,
        approval_request_id: str | None = None,
    ) -> None:
        if not self.on_call:
            return
        entry: dict[str, Any] = {
            'agent_id': agent_claims.get('agent_id'),
            'company_id': agent_claims.get('company_id'),
            'service': self.service_name,
            'tool': tool_name,
            # Identity ``McpInternalCallLogView`` accepts only JSON-RPC MCP traffic: POST ``/mcp``.
            'path': '/mcp',
            'method': 'POST',
            'resource_path': openapi_path_for_operation_id(schema, tool_name) or path_template,
            'http_method': method,
            'http_status': http_status,
            'access_kind': call_log_access_kind(
                upstream_method=method, tool_read_only=tool_read_only, destructive=destructive
            ),
            'outcome': outcome,
            'error_code': error_code,
            'duration_ms': duration_ms,
            **authority_context_for_call_log(agent_claims),
        }
        if approval_request_id:
            entry['approval_request_id'] = approval_request_id
        self.on_call(entry)

    def handle(self, request: HttpRequest, *, agent_claims: dict[str, Any] | None) -> JsonResponse:
        if request.method != 'POST':
            return JsonResponse({'error': 'method_not_allowed'}, status=405)
        if agent_claims is None:
            return JsonResponse({'error': 'unauthorized'}, status=401)
        agent_id = str(agent_claims.get('agent_id') or '')
        if not agent_id:
            return JsonResponse({'error': 'unauthorized'}, status=401)
        if check_agent_rate_limit(agent_id):
            return JsonResponse({'error': 'rate_limited'}, status=429)
        if mcp_personal_agent_rejected(agent_claims):
            return JsonResponse({'error': 'forbidden'}, status=403)
        auth_reason, authority_ok = delegated_live_authority_state(agent_claims)
        if not authority_ok:
            if auth_reason in (DELEGATED_AUTH_REASON_UNAVAILABLE, DELEGATED_AUTH_REASON_MISCONFIGURED):
                return JsonResponse({'error': 'service_unavailable'}, status=503)
            return JsonResponse({'error': 'forbidden'}, status=403)
        company_id = agent_claims.get('company_id')
        try:
            company_id_int = strict_non_negative_int_optional(company_id, field='company_id')
        except ValueError:
            company_id_int = None
        if self.identity_revocation_check and self.identity_revocation_check(agent_id, company_id_int):
            return JsonResponse({'error': 'agent_revoked'}, status=403)
        if not self._service_allowed(agent_claims, self.service_name):
            return JsonResponse({'error': 'forbidden'}, status=403)
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'invalid_json'}, status=400)
        method = payload.get('method')
        req_id = payload.get('id')
        params = payload.get('params') or {}
        if method == 'initialize':
            return JsonResponse(self._result(req_id, {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}}))
        if method == 'tools/list':
            schema = self.schema_provider()
            tools = [{k: v for k, v in t.items() if not k.startswith('_')} for t in tools_from_schema(schema)]
            return JsonResponse(self._result(req_id, {'tools': tools}))
        if method == 'tools/call':
            return self._tools_call(request, req_id, params, agent_claims)
        return JsonResponse(self._error(req_id, -32601, 'Method not found'))

    def _tools_call(
        self,
        request: HttpRequest,
        req_id: Any,
        params: dict[str, Any],
        agent_claims: dict[str, Any],
    ) -> JsonResponse:
        tool_name = str(params.get('name') or '')
        arguments = params.get('arguments') or {}
        if agent_claims.get('agent_id'):
            arguments = _strip_agent_company_overrides(arguments if isinstance(arguments, dict) else {})
        schema = self.schema_provider()
        tools = tools_from_schema(schema)
        tool = next((t for t in tools if t['name'] == tool_name), None)
        if tool is None:
            return JsonResponse(self._error(req_id, -32602, 'Unknown tool'))
        meta = tool.get('_meta') or {}
        path_template = str(meta.get('path') or '')
        path = str(arguments.get('path') or path_template)
        method = str(arguments.get('method') or meta.get('method') or 'GET').upper()
        if path != path_template or method != meta.get('method'):
            return JsonResponse(self._error(req_id, -32602, 'Tool path mismatch'))
        try:
            validate_mcp_tool_arguments(arguments if isinstance(arguments, dict) else {}, meta)
            path_params = arguments.get('path_params') if isinstance(arguments.get('path_params'), dict) else {}
            resolved_path = materialize_openapi_path(path_template, path_params)
        except McpToolArgumentError as exc:
            return JsonResponse(self._error(req_id, -32602, str(exc)))

        access = str(agent_claims.get('mcp_access') or 'read_only')
        read_level = str(agent_claims.get('mcp_read') or 'safe')
        operation = self._operation(schema, path_template, method)
        destructive = bool(meta.get('destructive')) or is_destructive_operation(operation)
        tool_read_only = bool(meta.get('read_only'))
        response_markers = marker_tree_for_operation_response(operation, schema)
        decision = decide_write(
            method=method,
            access_mode=access,
            destructive=destructive,
            allow_destructive_without_asking=bool(agent_claims.get('mcp_destructive')),
            tool_read_only=tool_read_only,
        )
        if decision.needs_approval:
            if is_exchange_delegated_regional_agent(agent_claims):
                self._forward_call_log(
                    schema=schema,
                    agent_claims=agent_claims,
                    tool_name=tool_name,
                    path_template=path_template,
                    method=method,
                    tool_read_only=tool_read_only,
                    destructive=destructive,
                    duration_ms=0,
                    http_status=403,
                    outcome=OUTCOME_DENIED,
                    error_code='forbidden',
                )
                return JsonResponse(
                    self._result(
                        req_id,
                        {
                            'content': [
                                {
                                    'type': 'text',
                                    'text': 'Approve write tools in your company regional AI gateway. Hosting does not create those approvals.',
                                }
                            ],
                            'isError': True,
                        },
                    )
                )
            args_hash = hashlib.sha256(json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()
            approval_payload = {
                'agent_id': agent_claims.get('agent_id'),
                'company_id': agent_claims.get('company_id'),
                'service': self.service_name,
                'action': tool_name,
                'arguments': arguments,
                'arguments_hash': args_hash,
                'path': resolved_path,
                'method': method,
            }
            granted = False
            state = None
            approval_started = time.perf_counter()
            if self.approval_state:
                state = self.approval_state(approval_payload, use_mcp_approval_protocol=True)
                if state == 'executed':
                    self._forward_call_log(
                        schema=schema,
                        agent_claims=agent_claims,
                        tool_name=tool_name,
                        path_template=path_template,
                        method=method,
                        tool_read_only=tool_read_only,
                        destructive=destructive,
                        duration_ms=max(0, int((time.perf_counter() - approval_started) * 1000)),
                        http_status=410,
                        outcome=OUTCOME_FAILED,
                        error_code='approval_expired',
                    )
                    return JsonResponse(
                        self._result(
                            req_id,
                            {'content': [{'type': 'text', 'text': 'Approval expired.'}], 'isError': True},
                        )
                    )
                if state == 'approved':
                    approval_id = approval_payload.get('approval_id')
                    if approval_id and self.approval_consume:
                        consumed = self.approval_consume(str(approval_id), approval_payload)
                        if consumed:
                            granted = True
                    else:
                        _fail_o, _fail_e = outcome_and_error_for_http(503)
                        self._forward_call_log(
                            schema=schema,
                            agent_claims=agent_claims,
                            tool_name=tool_name,
                            path_template=path_template,
                            method=method,
                            tool_read_only=tool_read_only,
                            destructive=destructive,
                            duration_ms=max(0, int((time.perf_counter() - approval_started) * 1000)),
                            http_status=503,
                            outcome=_fail_o,
                            error_code=_fail_e,
                        )
                        return JsonResponse(
                            self._result(
                                req_id,
                                {'content': [{'type': 'text', 'text': 'Approval unavailable.'}], 'isError': True},
                            )
                        )
                elif state == 'pending':
                    self._forward_call_log(
                        schema=schema,
                        agent_claims=agent_claims,
                        tool_name=tool_name,
                        path_template=path_template,
                        method=method,
                        tool_read_only=tool_read_only,
                        destructive=destructive,
                        duration_ms=max(0, int((time.perf_counter() - approval_started) * 1000)),
                        http_status=0,
                        outcome=OUTCOME_WAITING_APPROVAL,
                        error_code='approval_pending',
                    )
                    return JsonResponse(
                        self._result(
                            req_id,
                            {
                                'content': [{'type': 'text', 'text': 'Approval pending.'}],
                                'isError': True,
                                'meta': {'status': 'pending'},
                            },
                        )
                    )
                elif state == APPROVAL_LOOKUP_UNAVAILABLE:
                    _fail_o, _fail_e = outcome_and_error_for_http(503)
                    self._forward_call_log(
                        schema=schema,
                        agent_claims=agent_claims,
                        tool_name=tool_name,
                        path_template=path_template,
                        method=method,
                        tool_read_only=tool_read_only,
                        destructive=destructive,
                        duration_ms=max(0, int((time.perf_counter() - approval_started) * 1000)),
                        http_status=503,
                        outcome=_fail_o,
                        error_code=_fail_e,
                    )
                elif state is None:
                    _fail_o, _fail_e = outcome_and_error_for_http(503)
                    self._forward_call_log(
                        schema=schema,
                        agent_claims=agent_claims,
                        tool_name=tool_name,
                        path_template=path_template,
                        method=method,
                        tool_read_only=tool_read_only,
                        destructive=destructive,
                        duration_ms=max(0, int((time.perf_counter() - approval_started) * 1000)),
                        http_status=503,
                        outcome=_fail_o,
                        error_code=_fail_e,
                    )
            if not granted and self.approval_handler:
                if state != APPROVAL_LOOKUP_UNAVAILABLE:
                    pending = self.approval_handler(approval_payload)
                    if pending:
                        appr_id = pending.get('id')
                        self._forward_call_log(
                            schema=schema,
                            agent_claims=agent_claims,
                            tool_name=tool_name,
                            path_template=path_template,
                            method=method,
                            tool_read_only=tool_read_only,
                            destructive=destructive,
                            duration_ms=max(0, int((time.perf_counter() - approval_started) * 1000)),
                            http_status=0,
                            outcome=OUTCOME_WAITING_APPROVAL,
                            error_code='approval_pending',
                            approval_request_id=str(appr_id) if appr_id else None,
                        )
                        return JsonResponse(
                            self._result(
                                req_id,
                                {
                                    'content': [{'type': 'text', 'text': 'Approval required.'}],
                                    'isError': True,
                                    'meta': {'approval_id': appr_id, 'status': 'pending'},
                                },
                            )
                        )
            if not granted:
                self._forward_call_log(
                    schema=schema,
                    agent_claims=agent_claims,
                    tool_name=tool_name,
                    path_template=path_template,
                    method=method,
                    tool_read_only=tool_read_only,
                    destructive=destructive,
                    duration_ms=max(0, int((time.perf_counter() - approval_started) * 1000)),
                    http_status=403,
                    outcome=OUTCOME_DENIED,
                    error_code='forbidden',
                )
                return JsonResponse(
                    self._result(
                        req_id,
                        {'content': [{'type': 'text', 'text': decision.reason or 'Forbidden'}], 'isError': True},
                    )
                )
        # Destructive tools stay ``allowed=False`` after a consumed approval. Do not apply that
        # flag again once the approval block has granted the call.
        elif not decision.allowed:
            self._forward_call_log(
                schema=schema,
                agent_claims=agent_claims,
                tool_name=tool_name,
                path_template=path_template,
                method=method,
                tool_read_only=tool_read_only,
                destructive=destructive,
                duration_ms=0,
                http_status=403,
                outcome=OUTCOME_DENIED,
                error_code='forbidden',
            )
            return JsonResponse(
                self._result(
                    req_id,
                    {'content': [{'type': 'text', 'text': decision.reason or 'Forbidden'}], 'isError': True},
                )
            )

        inner_kwargs = _dispatch_kwargs(
            method,
            arguments if isinstance(arguments, dict) else {},
            request.META.get('HTTP_AUTHORIZATION', ''),
        )
        drf_request = self._factory.generic(method, resolved_path, **inner_kwargs)
        self._attach_request_principal(drf_request, request, agent_claims)
        started = time.perf_counter()
        try:
            match = resolve(resolved_path, urlconf=self.urlconf)
        except Resolver404:
            return JsonResponse(self._error(req_id, -32602, 'Tool path did not resolve'))
        response = match.func(drf_request, *match.args, **match.kwargs)
        status_code = getattr(response, 'status_code', 500)
        try:
            data = response.data  # type: ignore[attr-defined]
        except AttributeError:
            data = {'detail': 'ok'}
        read_sensitive = read_level == 'sensitive'
        redacted = _public_tool_payload(
            data,
            read_sensitive=read_sensitive,
            markers=response_markers,
            tool_name=tool_name,
        )
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        outcome, error_code = outcome_and_error_for_http(status_code)

        self._forward_call_log(
            schema=schema,
            agent_claims=agent_claims,
            tool_name=tool_name,
            path_template=path_template,
            method=method,
            tool_read_only=tool_read_only,
            destructive=destructive,
            duration_ms=duration_ms,
            http_status=status_code,
            outcome=outcome,
            error_code=error_code,
        )
        return JsonResponse(
            self._result(
                req_id,
                {
                    'content': [{'type': 'text', 'text': json.dumps(redacted, cls=DjangoJSONEncoder)}],
                    'isError': outcome != OUTCOME_ALLOWED,
                },
            )
        )
