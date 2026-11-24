"""OpenTelemetry spans and the removed Prometheus routes."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import jwt
from django.test import TestCase, override_settings
from django.utils import timezone
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rest_framework.test import APIClient

from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, Deployment, DeploymentStatus
from config.request_context import RequestIdFilter, request_id_var
from shellui_django.telemetry import TraceContextFormatter, _reset_for_tests

_CLEARED_ENV = (
    'OTEL_EXPORTER_OTLP_ENDPOINT',
    'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT',
    'OTEL_EXPORTER_OTLP_METRICS_ENDPOINT',
    'OTEL_EXPORTER_OTLP_PROTOCOL',
    'OTEL_EXPORTER_OTLP_TRACES_PROTOCOL',
    'OTEL_EXPORTER_OTLP_METRICS_PROTOCOL',
    'OTEL_SDK_DISABLED',
    'OTEL_TRACES_EXPORTER',
    'OTEL_METRICS_EXPORTER',
    'OTEL_SERVICE_NAME',
    'OTEL_RESOURCE_ATTRIBUTES',
)


def _make_token(*, company_id: int = 10, is_staff: bool = False) -> str:
    return jwt.encode(
        {
            'sub': '1',
            'user_id': 1,
            'company_id': company_id,
            'email': 'user@example.com',
            'user_metadata': {'is_staff': is_staff, 'is_company_owner': True},
            'exp': 2**31 - 1,
        },
        'test-secret',
        algorithm='HS256',
    )


def _seed_company(*, company_id: int, name: str, artifact_size: int = 100) -> None:
    CompanyHostingAccess.objects.get_or_create(
        company_id=company_id,
        defaults={'status': AccessStatus.APPROVED},
    )
    app = App.objects.create(
        name=name,
        slug=f'{name}-slug',
        company_id=company_id,
        display_name=name.title(),
        created_by_id=1,
    )
    Deployment.objects.create(
        app=app,
        app_version='1.0.0',
        shellui_version='0.5.0',
        status=DeploymentStatus.ACTIVE,
        storage_prefix=f'co/{company_id}/{app.id}/1.0.0',
        artifact_size=artifact_size,
        finalized_at=timezone.now(),
    )


def _points(data, name: str):
    found = []
    if data is None:
        return found
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    found.extend(metric.data.data_points)
    return found


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    HOSTING_REGION='EU',
)
class TelemetryTests(TestCase):
    def setUp(self):
        self._saved_env = {key: os.environ.get(key) for key in _CLEARED_ENV}
        for key in _CLEARED_ENV:
            os.environ.pop(key, None)
        self.client = APIClient()
        self.jwks_patch = patch('apps.authapi.authentication.get_jwks_client')
        mock_client = self.jwks_patch.start()
        mock_client.return_value.get_signing_key.return_value = None
        self.addCleanup(self.jwks_patch.stop)
        self.addCleanup(self._shutdown_telemetry)

    def _shutdown_telemetry(self):
        _reset_for_tests()
        from config.telemetry import reset_metric_registration

        reset_metric_registration()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _enable(self):
        from config.telemetry import setup_service_telemetry

        span_exporter = InMemorySpanExporter()
        metric_reader = InMemoryMetricReader()
        self.assertTrue(
            setup_service_telemetry(span_exporter=span_exporter, metric_reader=metric_reader)
        )
        return span_exporter, metric_reader

    def test_metrics_routes_are_gone(self):
        for path in ('/hosting/v1/metrics', '/hosting/v1/metrics/all'):
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(
                self.client.get(path, HTTP_AUTHORIZATION=f'Bearer {_make_token()}').status_code,
                404,
            )

    def test_request_span_carries_shellui_ids(self):
        _seed_company(company_id=10, name='alpha')
        span_exporter, _reader = self._enable()
        response = self.client.get(
            '/hosting/v1/apps',
            HTTP_AUTHORIZATION=f'Bearer {_make_token()}',
        )
        self.assertEqual(response.status_code, 200)
        spans = span_exporter.get_finished_spans()
        self.assertTrue(spans)
        matched = [
            span
            for span in spans
            if dict(span.attributes or {}).get('shellui.company_id') == '10'
        ]
        self.assertTrue(matched)
        attributes = dict(matched[-1].attributes)
        self.assertEqual(attributes['shellui.user_id'], '1')
        self.assertEqual(attributes['shellui.region'], 'EU')
        self.assertNotIn('shellui.email', attributes)
        self.assertNotIn('user@example.com', str(attributes))
        from opentelemetry import trace

        resource = trace.get_tracer_provider().resource.attributes
        self.assertEqual(resource['service.name'], 'hosting-service')

    def test_log_record_carries_trace_ids(self):
        self._enable()
        from opentelemetry import trace

        captured: list[logging.LogRecord] = []

        class _Handler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        log = logging.getLogger('apps.hosting.telemetry')
        handler = _Handler()
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        token = request_id_var.set('-')
        try:
            with trace.get_tracer('hosting.test').start_as_current_span('request') as span:
                log.info('hello')
                context = span.get_span_context()
            record = captured[-1]
            self.assertEqual(record.trace_id, format(context.trace_id, '032x'))
            self.assertEqual(record.span_id, format(context.span_id, '016x'))
            RequestIdFilter().filter(record)
            text = TraceContextFormatter(
                '[req={request_id}] trace_id={trace_id} span_id={span_id} {message}',
                style='{',
            ).format(record)
            self.assertIn(record.trace_id, text)
            self.assertIn(record.span_id, text)
            self.assertIn('[req=-]', text)
        finally:
            request_id_var.reset(token)
            log.removeHandler(handler)

    def test_formatter_defaults_when_telemetry_is_off(self):
        token = request_id_var.set('-')
        try:
            record = logging.LogRecord('apps.hosting', logging.INFO, __file__, 1, 'hello', (), None)
            RequestIdFilter().filter(record)
            text = TraceContextFormatter(
                '[req={request_id}] trace_id={trace_id} span_id={span_id} {message}',
                style='{',
            ).format(record)
        finally:
            request_id_var.reset(token)
        self.assertEqual(text, '[req=-] trace_id=0 span_id=0 hello')

    def test_hosting_and_scheduler_metrics(self):
        from shellui_django.telemetry import canonical_metric_name

        from apps.actions.scheduled_job_metrics import clear_snapshot_cache as clear_jobs
        from apps.hosting.metrics import clear_snapshot_cache as clear_hosting

        _seed_company(company_id=10, name='alpha', artifact_size=50)
        _seed_company(company_id=11, name='beta', artifact_size=200)
        _span_exporter, reader = self._enable()
        clear_hosting()
        clear_jobs()
        data = reader.get_metrics_data()

        apps = {
            point.attributes['company_id']: point.value
            for point in _points(data, canonical_metric_name('shellui_hosting_apps_total'))
        }
        self.assertEqual(apps, {'10': 1, '11': 1})
        artifacts = {
            point.attributes['company_id']: point.value
            for point in _points(data, canonical_metric_name('shellui_hosting_artifact_bytes'))
        }
        self.assertEqual(artifacts['10'], 50)
        self.assertEqual(artifacts['11'], 200)
        enabled = _points(data, canonical_metric_name('shellui_hosting_scheduler_enabled'))
        self.assertEqual(len(enabled), 1)
        runs = _points(data, canonical_metric_name('shellui_hosting_scheduled_job_runs_total'))
        self.assertTrue(any(point.attributes['job'] == 'retry_webhooks' for point in runs))
        self.assertTrue(_points(data, canonical_metric_name('shellui_hosting_scheduled_job_overdue')))
