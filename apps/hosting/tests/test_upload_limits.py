"""Upload size limits: streamed bodies never hit DATA_UPLOAD_MAX_MEMORY_SIZE."""

from __future__ import annotations

import io
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, Deployment
from apps.hosting.storage import ArtifactTooLarge, save_artifact
from apps.hosting.tests.test_access import make_token
from apps.hosting.tests.test_deploy_tokens import _tarball


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    IDENTITY_SERVICE_URL='',
    HOSTING_DEBUG_OPEN=False,
)
class UploadLimitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        p = patch('apps.authapi.authentication.get_jwks_client')
        p.start().return_value.get_signing_key.return_value = None
        self.addCleanup(p.stop)
        CompanyHostingAccess.objects.create(company_id=10, status=AccessStatus.APPROVED)
        self.app = App.objects.create(
            name='p', slug='p-abc', company_id=10, display_name='P', created_by_id=1,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.dep = Deployment.objects.create(app=self.app, app_version='1.0.0', shellui_version='0.7.0', deployed_by_id=1, storage_prefix='t')
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {make_token(company_id=10, is_company_owner=True, user_id=1)}'}

    def put(self, data, **extra):
        return self.client.put(
            f'/hosting/v1/apps/p-abc/deployments/{self.dep.id}/upload',
            data=data, content_type='application/gzip', **self.auth, **extra,
        )

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10)
    def test_body_over_django_memory_limit_still_uploads(self):
        res = self.put(_tarball())
        self.assertEqual(res.status_code, 200, res.content)

    @override_settings(HOSTING_MAX_UPLOAD_BYTES=1024**2)
    def test_declared_size_over_limit_returns_413_detail(self):
        res = self.put(b'x' * (2 * 1024**2))
        self.assertEqual(res.status_code, 413)
        self.assertEqual(res.json()['detail'], 'Artifact is 2 MB, the limit is 1 MB.')
        self.assertEqual(res.json()['error'], 'upload_too_large')

    def test_save_artifact_stops_streaming_over_limit(self):
        with self.assertRaises(ArtifactTooLarge):
            save_artifact('k', io.BytesIO(b'x' * 200), max_bytes=100)

    def test_request_data_too_big_is_clean_json(self):
        from django.core.exceptions import RequestDataTooBig
        with patch('apps.hosting.views.Deployment.objects.get', side_effect=RequestDataTooBig('x')):
            res = self.put(_tarball())
        self.assertEqual(res.status_code, 413)
        self.assertIn('limit', res.json()['detail'])
