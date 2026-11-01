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


class HostingOpenApiMcpTests(SimpleTestCase):
    def test_spectacular_validate_fail_on_warn(self):
        with tempfile.NamedTemporaryFile(suffix='.yml') as handle:
            try:
                call_command(
                    'spectacular',
                    validate=True,
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

    def test_secret_field_names_documented(self):
        expected = sorted(f'{c}.{p}' for c, p in MCP_REQUIRED_SECRET_SCHEMA_PROPERTIES)
        self.assertIn('DeployTokenCreateResponse.token', expected)
