"""MCP artifact upload URL flow (bytes outside JSON-RPC)."""

from __future__ import annotations

import io
import json
import tarfile
import uuid
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, Deployment, DeploymentStatus
from apps.hosting.tests.signing_helpers import MCP_SIGNING_TEST_SETTINGS
from apps.hosting.tests.test_mcp import _agent_token, _clear_revocation_cache


def _site_tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        data = b'<html><body>mcp</body></html>'
        info = tarfile.TarInfo(name='index.html')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


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
)
class McpArtifactUploadFlowTests(TestCase):
    company_id = 42

    def setUp(self):
        CompanyHostingAccess.objects.create(company_id=self.company_id, status=AccessStatus.APPROVED)
        self.client = Client()
        self.agent_id = str(uuid.uuid4())
        self.token = _agent_token(agent_id=self.agent_id, company_id=self.company_id, mcp_access='full')
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
        from apps.hosting import mcp_views

        mcp_views._server = None

    def tearDown(self):
        self._delegated_live.stop()
        self._revocation_ok.stop()

    def _rpc(self, method: str, params: dict | None = None):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}
        return self.client.post(
            reverse('mcp'),
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )

    def _tool(self, name: str, arguments: dict):
        return self._rpc('tools/call', {'name': name, 'arguments': arguments})

    def _result_json(self, response) -> dict:
        text = response.json()['result']['content'][0]['text']
        return json.loads(text)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_tools_list_includes_upload_url_not_raw_put(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        response = self._rpc('tools/list')
        names = {t['name'] for t in response.json()['result']['tools']}
        self.assertIn('hosting_create_apps_deployments_artifact_upload_url', names)
        self.assertIn('hosting_create_apps_deployments_artifact_upload_complete', names)
        self.assertNotIn('hosting_v1_apps_deployments_upload_update', names)

    @patch('apps.authapi.authentication.get_jwks_client')
    def test_agent_deploys_via_upload_url_and_finalize(self, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        app = App.objects.create(
            name='mcp-site',
            slug='mcpsite01',
            company_id=self.company_id,
            display_name='MCP',
            created_by_id=1,
        )
        dep_id = uuid.uuid4()
        deployment = Deployment.objects.create(
            id=dep_id,
            app=app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=1,
            storage_prefix=f'{app.id}/deployments/{dep_id}/',
            status=DeploymentStatus.DRAFT,
        )

        url_resp = self._tool(
            'hosting_create_apps_deployments_artifact_upload_url',
            {
                'path': '/hosting/v1/apps/{app_ref}/deployments/{deployment_id}/artifact-upload-url',
                'method': 'POST',
                'path_params': {'app_ref': app.slug, 'deployment_id': str(deployment.id)},
            },
        )
        url_result = url_resp.json()['result']
        self.assertFalse(url_result.get('isError'), url_result['content'][0]['text'])
        upload_meta = json.loads(url_result['content'][0]['text'])
        self.assertEqual(upload_meta['method'], 'PUT')
        self.assertTrue(upload_meta['requires_bearer'])
        self.assertEqual(upload_meta['backend'], 'direct')
        # Safe-read agents must still see the hosting PUT URL. It is not a credential.
        self.assertIn(str(deployment.id), upload_meta['upload_url'])
        self.assertNotEqual(upload_meta['upload_url'], '[redacted]')

        tarball = _site_tarball()
        upload_path = reverse(
            'hosting-deployment-upload',
            kwargs={'app_ref': app.slug, 'deployment_id': deployment.id},
        )
        put_resp = self.client.put(
            upload_path,
            data=tarball,
            content_type='application/gzip',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(put_resp.status_code, 200)

        complete_resp = self._tool(
            'hosting_create_apps_deployments_artifact_upload_complete',
            {
                'path': '/hosting/v1/apps/{app_ref}/deployments/{deployment_id}/artifact-upload-complete',
                'method': 'POST',
                'path_params': {'app_ref': app.slug, 'deployment_id': str(deployment.id)},
            },
        )
        self.assertFalse(complete_resp.json()['result'].get('isError'))
        complete_body = self._result_json(complete_resp)
        self.assertGreaterEqual(int(complete_body['artifact_size']), len(tarball) // 4)

        def _approved(payload, use_mcp_approval_protocol=True):
            payload['approval_id'] = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            return 'approved'

        from apps.hosting import mcp_views

        with (
            patch('apps.hosting.mcp_views.approval_state', _approved),
            patch('apps.hosting.mcp_views.consume_approval', return_value=True),
        ):
            mcp_views._server = None
            finalize_resp = self._tool(
                'hosting_create_apps_deployments_finalize',
                {
                    'app_ref': app.slug,
                    'deployment_id': str(deployment.id),
                },
            )
        self.assertFalse(finalize_resp.json()['result'].get('isError'))
        finalized = self._result_json(finalize_resp)
        self.assertEqual(finalized['status'], DeploymentStatus.ACTIVE)

    @patch('apps.authapi.authentication.get_jwks_client')
    @patch('apps.hosting.storage.is_s3_backend', return_value=True)
    @patch('apps.hosting.storage.presigned_artifact_put_url', return_value='https://s3.example.com/presigned-put')
    def test_s3_upload_url_then_complete(self, _mock_presign, _mock_s3, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        # Presigned URLs are x-mcp-sensitive; safe read mode redacts them before assert.
        prev_token = self.token
        self.token = _agent_token(
            agent_id=self.agent_id,
            company_id=self.company_id,
            mcp_access='full',
            mcp_read='sensitive',
        )
        app = App.objects.create(
            name='s3-site',
            slug='s3site01',
            company_id=self.company_id,
            display_name='S3',
            created_by_id=1,
        )
        dep_id = uuid.uuid4()
        deployment = Deployment.objects.create(
            id=dep_id,
            app=app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=1,
            storage_prefix=f'{app.id}/deployments/{dep_id}/',
            status=DeploymentStatus.DRAFT,
        )

        url_resp = self._tool(
            'hosting_create_apps_deployments_artifact_upload_url',
            {
                'path': '/hosting/v1/apps/{app_ref}/deployments/{deployment_id}/artifact-upload-url',
                'method': 'POST',
                'path_params': {'app_ref': app.slug, 'deployment_id': str(deployment.id)},
            },
        )
        meta = self._result_json(url_resp)
        self.assertEqual(meta['backend'], 's3')
        self.assertFalse(meta['requires_bearer'])
        self.assertEqual(meta['upload_url'], 'https://s3.example.com/presigned-put')

        tarball = _site_tarball()
        with patch('django.core.files.storage.default_storage.exists', return_value=True), patch(
            'django.core.files.storage.default_storage.size', return_value=len(tarball)
        ):
            complete_resp = self._tool(
                'hosting_create_apps_deployments_artifact_upload_complete',
                {
                    'path': '/hosting/v1/apps/{app_ref}/deployments/{deployment_id}/artifact-upload-complete',
                    'method': 'POST',
                    'path_params': {'app_ref': app.slug, 'deployment_id': str(deployment.id)},
                },
            )
        self.assertFalse(complete_resp.json()['result'].get('isError'))
        deployment.refresh_from_db()
        self.assertEqual(deployment.artifact_size, len(tarball))
        self.token = prev_token

    @patch('apps.authapi.authentication.get_jwks_client')
    @patch('apps.hosting.storage.is_s3_backend', return_value=True)
    @patch('apps.hosting.storage.presigned_artifact_put_url', return_value='https://s3.example.com/presigned-put')
    def test_s3_upload_url_stays_masked_for_safe_read(self, _mock_presign, _mock_s3, mock_jwks):
        mock_jwks.return_value.get_signing_key.return_value = None
        app = App.objects.create(
            name='s3-safe',
            slug='s3safe01',
            company_id=self.company_id,
            display_name='S3 safe',
            created_by_id=1,
        )
        dep_id = uuid.uuid4()
        deployment = Deployment.objects.create(
            id=dep_id,
            app=app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=1,
            storage_prefix=f'{app.id}/deployments/{dep_id}/',
            status=DeploymentStatus.DRAFT,
        )
        url_resp = self._tool(
            'hosting_create_apps_deployments_artifact_upload_url',
            {
                'path': '/hosting/v1/apps/{app_ref}/deployments/{deployment_id}/artifact-upload-url',
                'method': 'POST',
                'path_params': {'app_ref': app.slug, 'deployment_id': str(deployment.id)},
            },
        )
        meta = self._result_json(url_resp)
        self.assertFalse(url_resp.json()['result'].get('isError'), meta)
        self.assertEqual(meta['backend'], 's3')
        self.assertEqual(meta['upload_url'], '[redacted]')
        self.assertNotIn('presigned-put', url_resp.content.decode())
