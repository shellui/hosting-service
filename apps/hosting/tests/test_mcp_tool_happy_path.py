"""One real ``tools/call`` happy path per Shellui MCP tool.

Calls go through ``POST /mcp`` with an agent JWT, company scope from that token,
and the same approval gate production uses. Destructive tools are granted a
single-use approval. Identity is not running here, so that grant is a test double
of the approval state and consume calls. Webhook sample delivery does not open a
network connection.
"""

from __future__ import annotations

import io
import json
import tarfile
import uuid
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.actions.models import ActionOutbox, ActionRule, EventLog
from apps.authapi.mcp_openapi import MCP_EXPLICIT_REGISTRY, MCP_REQUIRED_OPERATION_IDS
from apps.hosting.deploy_tokens import create_deploy_token
from apps.hosting.env_crypto import encrypt_env_value
from apps.hosting.models import (
    AccessStatus,
    App,
    AppCustomDomain,
    AppEnvironmentVariable,
    CompanyHostingAccess,
    Deployment,
    DeploymentStatus,
    HostedAppRequestLog,
)
from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS
from apps.hosting.tests.test_mcp import _agent_token, _clear_revocation_cache


def _site_tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        data = b'<html><body>audit</body></html>'
        info = tarfile.TarInfo(name='index.html')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@contextmanager
def _granted_approval():
    def _state(payload, use_mcp_approval_protocol=True):
        payload['approval_id'] = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        return 'approved'

    def _consume(approval_id, route_payload=None):
        return True

    with (
        patch('apps.hosting.mcp_views.approval_state', _state),
        patch('apps.hosting.mcp_views.consume_approval', _consume),
    ):
        from apps.hosting import mcp_views

        mcp_views._server = None
        try:
            yield
        finally:
            mcp_views._server = None


@override_settings(
    **MCP_SIGNING_TEST_SETTINGS,
    DEBUG=True,
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_AUDIENCE='',
    IDENTITY_ISSUER='',
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    HOSTING_MCP_RESOURCE='http://127.0.0.1/mcp',
    HOSTING_BACKEND='filesystem',
    IDENTITY_SERVICE_URL='',
    HOSTING_APP_DOMAIN='shellui.local',
)
class McpToolHappyPathTests(TestCase):
    company_id = 42

    def setUp(self):
        cache.clear()
        CompanyHostingAccess.objects.create(company_id=self.company_id, status=AccessStatus.APPROVED)
        self.client = Client()
        self.agent_id = str(uuid.uuid4())
        self.token = _agent_token(
            agent_id=self.agent_id,
            company_id=self.company_id,
            mcp_access='full',
            mcp_read='safe',
        )
        _clear_revocation_cache(self.company_id)
        self._revocation_ok = patch(
            'apps.hosting.mcp_revocation.fetch_revocation_payload',
            return_value={'revoked_agent_ids': []},
        )
        self._revocation_ok.start()
        self._delegated_live = patch(
            'apps.hosting.mcp_server.delegated_live_authority_state',
            return_value=('ok', True),
        )
        self._delegated_live.start()
        self._jwks = patch('apps.authapi.authentication.get_jwks_client')
        jwks = self._jwks.start()
        jwks.return_value.get_signing_key.return_value = None
        from apps.hosting import mcp_views

        mcp_views._server = None

        self.app = App.objects.create(
            name='auditapp',
            slug='auditapp',
            company_id=self.company_id,
            display_name='Audit',
            created_by_id=1,
        )
        self.preview = App.objects.create(
            name='auditpreview',
            slug='auditpreview',
            company_id=self.company_id,
            display_name='Preview',
            created_by_id=0,
            expires_at=timezone.now() + timedelta(days=2),
        )
        draft_id = uuid.uuid4()
        self.draft = Deployment.objects.create(
            id=draft_id,
            app=self.app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=1,
            storage_prefix=f'{self.app.id}/deployments/{draft_id}/',
            status=DeploymentStatus.DRAFT,
        )
        self.rollback_target = Deployment.objects.create(
            app=self.app,
            app_version='0.9.0',
            shellui_version='0.5.0',
            deployed_by_id=1,
            storage_prefix='rollback/',
            status=DeploymentStatus.SUPERSEDED,
            artifact_size=128,
        )
        self.domain = AppCustomDomain.objects.create(app=self.app, hostname='audit.example.com')
        AppEnvironmentVariable.objects.create(
            app=self.app,
            key='AUDIT_FLAG',
            value_ciphertext=encrypt_env_value('present'),
        )
        self.deploy_token, self.deploy_token_secret = create_deploy_token(
            company_id=self.company_id,
            name='audit-ci',
            created_by_id=1,
        )
        self.rule = ActionRule.objects.create(
            company_id=self.company_id,
            name='Audit hook',
            description='fixture',
            event_type='hosting.app.created',
            config={'url': 'https://example.com/hooks/hosting', 'secret': 'fixture-secret-value'},
        )
        self.delivery = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            delivery_kind=ActionOutbox.KIND_WEBHOOK,
            event_type='hosting.app.created',
            envelope={'id': 'evt-audit', 'type': 'hosting.app.created', 'data': {}},
            status=ActionOutbox.STATUS_FAILED,
            last_error='timeout',
        )
        self.event = EventLog.objects.create(
            company_id=self.company_id,
            event_type='hosting.app.created',
            data={'app_id': str(self.app.id)},
        )
        HostedAppRequestLog.objects.create(
            app=self.app,
            method='GET',
            path='/index.html',
            status_code=200,
            request_id='req-audit',
        )
        self.ids = {
            'app_ref': self.app.slug,
            'deployment_id': str(self.draft.id),
            'domain_id': str(self.domain.id),
            'key': 'AUDIT_FLAG',
            'token_id': str(self.deploy_token.id),
            'delivery_id': str(self.delivery.id),
            'id': str(self.rule.pk),
            'pk': str(self.event.pk),
        }
        self.by_name = {}

    def tearDown(self):
        self._jwks.stop()
        self._delegated_live.stop()
        self._revocation_ok.stop()

    def _ensure_catalog(self):
        if self.by_name:
            return
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}
        response = self.client.post(
            reverse('mcp'),
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.by_name = {tool['name']: tool for tool in response.json()['result']['tools']}

    def _arguments(self, name, *, path_params=None, query=None, body=None):
        self._ensure_catalog()
        tool = self.by_name[name]
        props = tool['inputSchema']['properties']
        required = tool['inputSchema']['required']
        arguments = {'path': props['path']['const'], 'method': props['method']['enum'][0]}
        if 'path_params' in required:
            names = props['path_params']['required']
            supplied = dict(self.ids)
            if path_params:
                supplied.update(path_params)
            missing = [key for key in names if key not in supplied]
            self.assertEqual(missing, [], name)
            arguments['path_params'] = {key: supplied[key] for key in names}
        if query is not None:
            arguments['query'] = query
        if body is not None:
            arguments['body'] = body
        return arguments

    def _call_tool(self, name, *, path_params=None, query=None, body=None):
        arguments = self._arguments(name, path_params=path_params, query=query, body=body)
        approve = bool(MCP_EXPLICIT_REGISTRY[name]['destructive'])

        def _post():
            payload = {
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/call',
                'params': {'name': name, 'arguments': arguments},
            }
            return self.client.post(
                reverse('mcp'),
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_AUTHORIZATION=f'Bearer {self.token}',
            )

        if approve:
            with _granted_approval():
                response = _post()
        else:
            response = _post()
        self.assertEqual(response.status_code, 200, response.content[:1500])
        envelope = response.json()
        self.assertNotIn('error', envelope, envelope)
        result = envelope['result']
        self.assertFalse(result.get('isError'), result.get('content'))
        return json.loads(result['content'][0]['text'])

    def _put_draft_artifact(self):
        upload_path = reverse(
            'hosting-deployment-upload',
            kwargs={'app_ref': self.app.slug, 'deployment_id': self.draft.id},
        )
        response = self.client.put(
            upload_path,
            data=_site_tarball(),
            content_type='application/gzip',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, 200, response.content[:800])

    def _case_hosting_v1_access_request_create(self):
        body = self._call_tool('hosting_v1_access_request_create')
        self.assertEqual(body['company_id'], self.company_id)
        self.assertEqual(body['status'], AccessStatus.APPROVED)

    def _case_hosting_v1_preview_create(self):
        body = self._call_tool(
            'hosting_v1_preview_create',
            body={'display_name': 'New preview', 'app_version': '1.2.3', 'shellui_version': '0.5.0'},
        )
        self.assertTrue(body['slug'])
        self.assertEqual(body['deployment']['status'], DeploymentStatus.DRAFT)
        self.assertEqual(body['app']['company_id'], self.company_id)

    def _case_hosting_v1_apps_list(self):
        rows = self._call_tool('hosting_v1_apps_list')
        self.assertIsInstance(rows, list)
        self.assertIn(self.app.slug, {row['slug'] for row in rows})

    def _case_hosting_v1_apps_create(self):
        body = self._call_tool(
            'hosting_v1_apps_create',
            body={'name': 'audit-created', 'display_name': 'Created'},
        )
        self.assertEqual(body['name'], 'audit-created')
        self.assertTrue(body['slug'])
        self.assertEqual(body['company_id'], self.company_id)
        self.assertTrue(App.objects.filter(company_id=self.company_id, name='audit-created').exists())

    def _case_hosting_v1_apps_retrieve(self):
        body = self._call_tool('hosting_v1_apps_retrieve')
        self.assertEqual(body['slug'], self.app.slug)
        self.assertEqual(body['id'], str(self.app.id))

    def _case_hosting_v1_apps_destroy(self):
        self._call_tool('hosting_v1_apps_destroy')
        self.assertFalse(App.objects.filter(pk=self.app.pk).exists())

    def _case_hosting_v1_apps_renew_expiry_create(self):
        before = self.preview.expires_at
        body = self._call_tool(
            'hosting_v1_apps_renew_expiry_create',
            path_params={'app_ref': self.preview.slug},
        )
        self.assertEqual(body['slug'], self.preview.slug)
        self.preview.refresh_from_db()
        self.assertGreater(self.preview.expires_at, before)

    def _case_hosting_v1_apps_deployments_list(self):
        rows = self._call_tool('hosting_v1_apps_deployments_list')
        self.assertIsInstance(rows, list)
        self.assertIn(str(self.draft.id), {row['id'] for row in rows})

    def _case_hosting_v1_apps_deployments_create(self):
        body = self._call_tool(
            'hosting_v1_apps_deployments_create',
            body={'app_version': '1.1.0', 'shellui_version': '0.5.0'},
        )
        self.assertEqual(body['status'], DeploymentStatus.DRAFT)
        self.assertEqual(body['app_version'], '1.1.0')

    def _case_hosting_v1_apps_deployments_artifact_upload_url_create(self):
        body = self._call_tool(
            'hosting_v1_apps_deployments_artifact_upload_url_create',
            query={'expires_in': 120},
        )
        self.assertEqual(body['method'], 'PUT')
        self.assertEqual(body['backend'], 'direct')
        self.assertTrue(body['requires_bearer'])
        self.assertIn(str(self.draft.id), body['upload_url'])
        self.assertNotEqual(body['upload_url'], '[redacted]')

    def _case_hosting_v1_apps_deployments_artifact_upload_complete_create(self):
        self._put_draft_artifact()
        body = self._call_tool('hosting_v1_apps_deployments_artifact_upload_complete_create')
        self.assertGreater(int(body['artifact_size']), 0)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, DeploymentStatus.UPLOADING)

    def _case_hosting_v1_apps_deployments_finalize_create(self):
        self._put_draft_artifact()
        body = self._call_tool('hosting_v1_apps_deployments_finalize_create')
        self.assertEqual(body['status'], DeploymentStatus.ACTIVE)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_deployment_id, self.draft.id)

    def _case_hosting_v1_apps_deployments_rollback_create(self):
        body = self._call_tool(
            'hosting_v1_apps_deployments_rollback_create',
            path_params={'deployment_id': str(self.rollback_target.id)},
        )
        self.assertEqual(body['status'], DeploymentStatus.ACTIVE)
        self.assertEqual(body['id'], str(self.rollback_target.id))

    def _case_hosting_v1_deploy_tokens_retrieve(self):
        rows = self._call_tool('hosting_v1_deploy_tokens_retrieve')
        self.assertIsInstance(rows, list)
        self.assertIn(str(self.deploy_token.id), {row['id'] for row in rows})
        text = json.dumps(rows)
        self.assertNotIn(self.deploy_token_secret, text)
        self.assertNotIn('"token"', text)

    def _case_hosting_v1_deploy_tokens_revoke_create(self):
        body = self._call_tool('hosting_v1_deploy_tokens_revoke_create')
        self.assertIsNotNone(body.get('revoked_at'))
        self.deploy_token.refresh_from_db()
        self.assertIsNotNone(self.deploy_token.revoked_at)

    def _case_hosting_v1_stats_retrieve(self):
        body = self._call_tool('hosting_v1_stats_retrieve')
        self.assertEqual(body['company_id'], self.company_id)
        self.assertGreaterEqual(body['apps'], 1)

    def _case_hosting_v1_apps_domains_list(self):
        rows = self._call_tool('hosting_v1_apps_domains_list')
        self.assertIsInstance(rows, list)
        self.assertIn('audit.example.com', {row['hostname'] for row in rows})
        self.assertFalse(any(row['verified'] or row['serving'] for row in rows))

    def _case_hosting_v1_apps_domains_create(self):
        body = self._call_tool(
            'hosting_v1_apps_domains_create',
            body={'hostname': 'created.example.com'},
        )
        self.assertEqual(body['hostname'], 'created.example.com')
        self.assertFalse(body['verified'])
        self.assertFalse(body['serving'])
        self.assertIn('dns', body)

    def _case_hosting_v1_apps_domains_retrieve(self):
        body = self._call_tool('hosting_v1_apps_domains_retrieve')
        self.assertEqual(body['id'], str(self.domain.id))
        self.assertEqual(body['hostname'], 'audit.example.com')
        self.assertFalse(body['verified'])

    def _case_hosting_v1_apps_domains_destroy(self):
        self._call_tool('hosting_v1_apps_domains_destroy')
        self.assertFalse(AppCustomDomain.objects.filter(pk=self.domain.pk).exists())

    def _case_hosting_v1_apps_domains_refresh_create(self):
        body = self._call_tool('hosting_v1_apps_domains_refresh_create')
        self.assertEqual(body['status'], 'awaiting_platform')
        self.assertFalse(body['verified'])
        self.assertFalse(body['serving'])

    def _case_hosting_v1_apps_environment_list(self):
        rows = self._call_tool('hosting_v1_apps_environment_list')
        self.assertIsInstance(rows, list)
        match = next(row for row in rows if row['key'] == 'AUDIT_FLAG')
        self.assertTrue(match['value_present'])
        self.assertNotIn('"present"', json.dumps(rows))

    def _case_hosting_v1_apps_environment_create(self):
        body = self._call_tool(
            'hosting_v1_apps_environment_create',
            body={'key': 'CREATED_FLAG', 'value': 'super-secret-value'},
        )
        self.assertEqual(body['key'], 'CREATED_FLAG')
        self.assertTrue(body['value_present'])
        self.assertNotIn('super-secret-value', json.dumps(body))

    def _case_hosting_v1_apps_environment_retrieve(self):
        body = self._call_tool('hosting_v1_apps_environment_retrieve')
        self.assertEqual(body['key'], 'AUDIT_FLAG')
        self.assertTrue(body['value_present'])
        self.assertNotIn('value', body)

    def _case_hosting_v1_apps_environment_update(self):
        body = self._call_tool(
            'hosting_v1_apps_environment_update',
            body={'value': 'rotated-secret-value'},
        )
        self.assertEqual(body['key'], 'AUDIT_FLAG')
        self.assertTrue(body['value_present'])
        self.assertNotIn('rotated-secret-value', json.dumps(body))

    def _case_hosting_v1_apps_environment_destroy(self):
        self._call_tool('hosting_v1_apps_environment_destroy')
        self.assertFalse(AppEnvironmentVariable.objects.filter(app=self.app, key='AUDIT_FLAG').exists())

    def _case_hosting_v1_apps_runtime_logs_list(self):
        body = self._call_tool('hosting_v1_apps_runtime_logs_list', query={'limit': 5})
        self.assertEqual(body['source'], 'none')
        self.assertEqual(body['lines'], [])
        self.assertTrue(body['unavailable_reason'])

    def _case_hosting_v1_apps_request_logs_list(self):
        body = self._call_tool(
            'hosting_v1_apps_request_logs_list',
            query={'limit': 10, 'status_min': 200, 'status_max': 299},
        )
        self.assertEqual(body['limit'], 10)
        self.assertTrue(any(row['path'] == '/index.html' and row['status_code'] == 200 for row in body['results']))

    def _case_api_v1_actions_events_list(self):
        body = self._call_tool('api_v1_actions_events_list')
        types = {row['type'] for row in body['results']}
        self.assertIn('hosting.app.created', types)

    def _case_api_v1_actions_rules_list(self):
        body = self._call_tool('api_v1_actions_rules_list')
        self.assertIn(self.rule.pk, {row['id'] for row in body['results']})

    def _case_api_v1_actions_rules_create(self):
        body = self._call_tool(
            'api_v1_actions_rules_create',
            body={
                'name': 'Created hook',
                'event_type': 'hosting.app.created',
                'url': 'https://example.com/hooks/created',
            },
        )
        self.assertEqual(body['name'], 'Created hook')
        rule = ActionRule.objects.get(pk=body['id'])
        secret = (rule.config or {}).get('secret') or ''
        self.assertTrue(secret)
        self.assertNotIn(secret, json.dumps(body))
        self.assertEqual(body.get('secret'), '[redacted]')

    def _case_api_v1_actions_rules_retrieve(self):
        body = self._call_tool('api_v1_actions_rules_retrieve')
        self.assertEqual(body['id'], self.rule.pk)
        self.assertEqual(body['name'], 'Audit hook')
        self.assertNotIn('fixture-secret-value', json.dumps(body))

    def _case_api_v1_actions_rules_partial_update(self):
        body = self._call_tool(
            'api_v1_actions_rules_partial_update',
            body={'name': 'Renamed hook', 'enabled': True},
        )
        self.assertEqual(body['name'], 'Renamed hook')
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.name, 'Renamed hook')

    def _case_api_v1_actions_rules_destroy(self):
        self._call_tool('api_v1_actions_rules_destroy')
        self.assertFalse(ActionRule.objects.filter(pk=self.rule.pk).exists())

    def _case_api_v1_actions_rules_rotate_secret(self):
        before = (self.rule.config or {})['secret']
        body = self._call_tool('api_v1_actions_rules_rotate_secret')
        self.rule.refresh_from_db()
        after = (self.rule.config or {}).get('secret') or ''
        self.assertNotEqual(before, after)
        self.assertTrue(after)
        self.assertNotIn(after, json.dumps(body))
        self.assertEqual(body.get('secret'), '[redacted]')

    def _case_api_v1_actions_rules_send_test(self):
        with patch('apps.actions.webhook_test_send.deliver_webhook_action', return_value=None):
            body = self._call_tool('api_v1_actions_rules_send_test')
        self.assertTrue(body.get('ok'))
        self.assertEqual(body.get('event_type'), 'hosting.app.created')

    def _case_api_v1_actions_deliveries_list(self):
        body = self._call_tool('api_v1_actions_deliveries_list', query={'status': 'failed'})
        self.assertGreaterEqual(body['count'], 1)
        self.assertIn(str(self.delivery.id), {row['id'] for row in body['results']})

    def _case_api_v1_actions_deliveries_retrieve(self):
        body = self._call_tool('api_v1_actions_deliveries_retrieve')
        self.assertEqual(body['id'], str(self.delivery.id))
        self.assertEqual(body['status'], ActionOutbox.STATUS_FAILED)

    def _case_api_v1_actions_deliveries_requeue(self):
        body = self._call_tool('api_v1_actions_deliveries_requeue')
        self.assertEqual(body['status'], ActionOutbox.STATUS_PENDING)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, ActionOutbox.STATUS_PENDING)

    def _case_api_v1_actions_event_log_list(self):
        body = self._call_tool(
            'api_v1_actions_event_log_list',
            query={'event_type': 'hosting.app.created'},
        )
        self.assertGreaterEqual(body['count'], 1)
        self.assertTrue(any(row['event_type'] == 'hosting.app.created' for row in body['results']))

    def _case_api_v1_actions_event_log_retrieve(self):
        body = self._call_tool(
            'api_v1_actions_event_log_retrieve',
            path_params={'id': str(self.event.pk), 'pk': str(self.event.pk)},
        )
        self.assertEqual(body['event_type'], 'hosting.app.created')
        self.assertEqual(body['id'], self.event.pk)

    def _case_api_v1_actions_event_log_types_list(self):
        body = self._call_tool('api_v1_actions_event_log_types_list')
        self.assertTrue(body['results'])
        self.assertIn('type', body['results'][0])

    def _case_api_v1_actions_event_log_retention_retrieve(self):
        body = self._call_tool('api_v1_actions_event_log_retention_retrieve')
        self.assertIn('data_retention_days', body)
        self.assertGreaterEqual(body['data_retention_days'], 1)


def _bind(tool_name):
    def test(self):
        handler = getattr(self, f'_case_{tool_name}', None)
        if handler is None:
            self.fail(f'no happy-path tools/call for {tool_name}')
        handler()

    test.__name__ = f'test_{tool_name}'
    test.__doc__ = f'Happy-path tools/call for {tool_name}.'
    return test


for _tool_name in sorted(MCP_REQUIRED_OPERATION_IDS):
    setattr(McpToolHappyPathTests, f'test_{_tool_name}', _bind(_tool_name))
