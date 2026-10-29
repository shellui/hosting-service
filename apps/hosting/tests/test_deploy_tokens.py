"""Deploy tokens and production deploys."""

from __future__ import annotations

import io
import tarfile
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hosting.deploy_tokens import create_deploy_token, hash_token
from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, DeployToken
from apps.hosting.tests.test_access import make_token


def _tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        data = b'<html>prod</html>'
        info = tarfile.TarInfo(name='index.html')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    IDENTITY_SERVICE_URL='',
    HOSTING_DEBUG_OPEN=False,
)
class DeployTokenTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        p = patch('apps.authapi.authentication.get_jwks_client')
        p.start().return_value.get_signing_key.return_value = None
        self.addCleanup(p.stop)
        CompanyHostingAccess.objects.create(company_id=10, status=AccessStatus.APPROVED)
        self.app = App.objects.create(name='site', slug='site-abc', company_id=10, display_name='Site')
        self.other = App.objects.create(name='other', slug='other-abc', company_id=10, display_name='Other')

    def owner(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(company_id=10, is_company_owner=True)}'}

    def bearer(self, raw):
        return {'HTTP_AUTHORIZATION': f'Bearer {raw}'}

    def test_owner_creates_token_shown_once_and_stored_hashed(self):
        res = self.client.post('/hosting/v1/apps/site/deploy-tokens', {'name': 'GitHub'}, format='json', **self.owner())
        self.assertEqual(res.status_code, 201)
        raw = res.json()['token']
        self.assertTrue(raw.startswith('shellui_dt_'))
        stored = DeployToken.objects.get()
        self.assertEqual(stored.token_hash, hash_token(raw))
        self.assertNotIn(raw, str(stored.__dict__))
        listing = self.client.get('/hosting/v1/apps/site/deploy-tokens', **self.owner()).json()
        self.assertNotIn('token', listing[0])
        self.assertNotIn('token_hash', listing[0])

    def test_member_cannot_manage_tokens(self):
        member = {'HTTP_AUTHORIZATION': f'Bearer {make_token(company_id=10)}'}
        res = self.client.post('/hosting/v1/apps/site/deploy-tokens', {'name': 'x'}, format='json', **member)
        self.assertEqual(res.status_code, 403)

    def test_token_runs_production_deploy_end_to_end(self):
        _, raw = create_deploy_token(app=self.app, name='ci', created_by_id=1)
        res = self.client.post(
            '/hosting/v1/apps/site/production',
            {'app_version': '1.0.0', 'shellui_version': '0.7.0'},
            format='json',
            **self.bearer(raw),
        )
        self.assertEqual(res.status_code, 201, res.content)
        dep = res.json()['deployment']['id']
        up = self.client.put(
            f'/hosting/v1/apps/site/deployments/{dep}/upload',
            data=_tarball(),
            content_type='application/gzip',
            **self.bearer(raw),
        )
        self.assertEqual(up.status_code, 200, up.content)
        fin = self.client.post(f'/hosting/v1/apps/site/deployments/{dep}/finalize', **self.bearer(raw))
        self.assertEqual(fin.status_code, 200, fin.content)
        self.assertEqual(fin.json()['status'], 'active')
        self.assertIsNotNone(DeployToken.objects.get().last_used_at)
        promote = self.client.post(f'/hosting/v1/apps/site/deployments/{dep}/promote', **self.bearer(raw))
        self.assertEqual(promote.status_code, 200, promote.content)

    def test_token_is_deploy_only(self):
        _, raw = create_deploy_token(app=self.app, name='ci', created_by_id=1)
        self.assertEqual(self.client.get('/hosting/v1/apps', **self.bearer(raw)).status_code, 403)
        self.assertEqual(self.client.get('/hosting/v1/apps/site/deployments', **self.bearer(raw)).status_code, 403)
        self.assertEqual(self.client.get('/hosting/v1/apps/site/deploy-tokens', **self.bearer(raw)).status_code, 403)
        self.assertEqual(self.client.delete('/hosting/v1/apps/site', **self.bearer(raw)).status_code, 403)

    def test_token_wrong_app(self):
        _, raw = create_deploy_token(app=self.app, name='ci', created_by_id=1)
        res = self.client.post(
            '/hosting/v1/apps/other/production',
            {'app_version': '1.0.0', 'shellui_version': '0.7.0'},
            format='json',
            **self.bearer(raw),
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()['error'], 'deploy_token_wrong_app')

    def test_revoked_and_expired_and_invalid(self):
        token, raw = create_deploy_token(app=self.app, name='ci', created_by_id=1)
        rev = self.client.post(f'/hosting/v1/apps/site/deploy-tokens/{token.id}/revoke', **self.owner())
        self.assertEqual(rev.status_code, 200)
        res = self.client.post('/hosting/v1/apps/site/production', {}, format='json', **self.bearer(raw))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()['error'], 'deploy_token_revoked')
        self.assertNotIn(raw, res.content.decode())

        token2, raw2 = create_deploy_token(app=self.app, name='old', created_by_id=1, expires_in_days=1)
        DeployToken.objects.filter(id=token2.id).update(expires_at=timezone.now() - timedelta(seconds=1))
        res = self.client.post('/hosting/v1/apps/site/production', {}, format='json', **self.bearer(raw2))
        self.assertEqual(res.json()['error'], 'deploy_token_expired')

        res = self.client.post('/hosting/v1/apps/site/production', {}, format='json', **self.bearer('shellui_dt_nope'))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()['error'], 'deploy_token_invalid')

    def test_production_refuses_preview_apps(self):
        App.objects.create(name='prev', slug='prev-abc', company_id=10, display_name='P', created_by_id=1)
        res = self.client.post(
            '/hosting/v1/apps/prev/production',
            {'app_version': '1.0.0', 'shellui_version': '0.7.0'},
            format='json',
            **self.owner(),
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()['error'], 'not_production_app')
