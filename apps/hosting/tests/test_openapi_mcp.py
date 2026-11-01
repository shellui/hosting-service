"""OpenAPI schema must match Shellui MCP allowlists."""

from __future__ import annotations

import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.authapi.mcp_openapi import (
    MCP_EXCLUDED_PATH_PREFIXES,
    MCP_EXPLICIT_REGISTRY,
    MCP_REQUIRED_OPERATION_IDS,
    MCP_REQUIRED_SECRET_SCHEMA_PROPERTIES,
    validate_mcp_schema,
    validate_mcp_secret_fields,
)
from apps.hosting.openapi_mcp_registry import MCP_SPECS


class HostingOpenApiMcpTests(SimpleTestCase):
    def test_spectacular_validate_fail_on_warn(self):
        with tempfile.NamedTemporaryFile(suffix='.yml') as handle:
            try:
                call_command(
                    'spectacular',
                    validate=True,
                    fail_on_warn=True,
                    file=handle.name,
                    stdout=handle,
                )
            except CommandError as exc:
                self.fail(str(exc))

        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        validate_mcp_schema(schema)
        validate_mcp_secret_fields(schema)
        paths = schema.get('paths') or {}
        for prefix in MCP_EXCLUDED_PATH_PREFIXES:
            for path in paths:
                self.assertFalse(path.startswith(prefix), path)

    def test_registry_matches_allowlist(self):
        self.assertEqual(set(MCP_EXPLICIT_REGISTRY), MCP_REQUIRED_OPERATION_IDS)

    def test_mcp_openapi_registry_matches_allowlist(self):
        self.assertEqual(set(MCP_SPECS), MCP_REQUIRED_OPERATION_IDS)

    def test_mcp_operations_are_fully_documented(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = schema['paths']
        required_errors = {400, 401, 403, 404, 409, 429}
        for op_id in MCP_REQUIRED_OPERATION_IDS:
            operation = None
            for path_item in paths.values():
                for op in path_item.values():
                    if isinstance(op, dict) and op.get('operationId') == op_id:
                        operation = op
                        break
            self.assertIsNotNone(operation, op_id)
            assert operation is not None
            self.assertTrue(operation.get('summary'), op_id)
            self.assertTrue(operation.get('description'), op_id)
            response_codes = {int(code) for code in operation.get('responses', {}) if str(code).isdigit()}
            self.assertTrue(required_errors <= response_codes, (op_id, response_codes))
            description = operation['description']
            for needle in ('Side effects:', 'Sends email:', 'Destructive:', 'Permissions:'):
                self.assertIn(needle, description, op_id)

    def test_secret_field_names_documented(self):
        expected = sorted(f'{c}.{p}' for c, p in MCP_REQUIRED_SECRET_SCHEMA_PROPERTIES)
        self.assertIn('DeployTokenCreateResponse.token', expected)
