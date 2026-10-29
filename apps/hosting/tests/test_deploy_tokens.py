"""Company deploy tokens for CI preview deploys."""

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
        data = b'<html>preview</html>'
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
        self.admin_app = App.objects.create(name='site', slug='site-abc', company_id=10, display_name='Site')
        self.teammate_preview = App.objects.create(
            name='mate', slug='mate-abc', company_id=10, display_name='Mate', created_by_id=2,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.foreign_preview = App.objects.create(
            name='far', slug='far-abc', company_id=11, display_name='Far', created_by_id=3,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def owner(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(company_id=10, is_company_owner=True)}'}

    def bearer(self, raw):
        return {'HTTP_AUTHORIZATION': f'Bearer {raw}'}

    def prepare(self, raw, slug=None):
        body = {'app_version': '1.0.0', 'shellui_version': '0.7.0'}
        if slug:
            body['slug'] = slug
        return self.client.post('/hosting/v1/preview', body, format='json', **self.bearer(raw))

    def test_owner_creates_token_shown_once_and_stored_hashed(self):
        res = self.client.post('/hosting/v1/deploy-tokens', {'name': 'GitHub'}, format='json', **self.owner())
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res['Cache-Control'], 'no-store')
        raw = res.json()['token']
        self.assertTrue(raw.startswith('shellui_dt_'))
        stored = DeployToken.objects.get()
        self.assertEqual(stored.company_id, 10)
        self.assertEqual(stored.token_hash, hash_token(raw))
        self.assertNotIn(raw, str(stored.__dict__))
        listing = self.client.get('/hosting/v1/deploy-tokens', **self.owner()).json()
        self.assertNotIn('token', listing[0])
        self.assertNotIn('token_hash', listing[0])

    def test_member_cannot_manage_tokens(self):
        member = {'HTTP_AUTHORIZATION': f'Bearer {make_token(company_id=10)}'}
        res = self.client.post('/hosting/v1/deploy-tokens', {'name': 'x'}, format='json', **member)
        self.assertEqual(res.status_code, 403)

    def test_token_creates_preview_end_to_end(self):
        _, raw = create_deploy_token(company_id=10, name='ci', created_by_id=1)
        res = self.prepare(raw)
        self.assertEqual(res.status_code, 201, res.content)
        slug = res.json()['slug']
        self.assertEqual(App.objects.get(slug=slug).created_by_id, 1)
        dep = res.json()['deployment']['id']
        up = self.client.put(
            f'/hosting/v1/apps/{slug}/deployments/{dep}/upload',
            data=_tarball(),
            content_type='application/gzip',
            **self.bearer(raw),
        )
        self.assertEqual(up.status_code, 200, up.content)
        fin = self.client.post(f'/hosting/v1/apps/{slug}/deployments/{dep}/finalize', **self.bearer(raw))
        self.assertEqual(fin.status_code, 200, fin.content)
        self.assertEqual(fin.json()['status'], 'active')
        self.assertIsNotNone(DeployToken.objects.get().last_used_at)
        self.assertEqual(self.prepare(raw, slug).status_code, 201)

    def test_token_redeploys_any_company_preview(self):
        _, raw = create_deploy_token(company_id=10, name='ci', created_by_id=1)
        self.assertEqual(self.prepare(raw, 'mate-abc').status_code, 201)

    def test_token_refuses_admin_apps_and_other_companies(self):
        _, raw = create_deploy_token(company_id=10, name='ci', created_by_id=1)
        res = self.prepare(raw, 'site-abc')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()['error'], 'deploy_token_preview_only')
        self.assertEqual(self.prepare(raw, 'far-abc').status_code, 403)
        dep = self.admin_app.deployments.create(app_version='1.0.0', shellui_version='0.7.0')
        res = self.client.post(f'/hosting/v1/apps/site/deployments/{dep.id}/finalize', **self.bearer(raw))
        self.assertEqual(res.status_code, 403)

    def test_token_is_preview_deploy_only(self):
        _, raw = create_deploy_token(company_id=10, name='ci', created_by_id=1)
        self.assertEqual(self.client.get('/hosting/v1/apps', **self.bearer(raw)).status_code, 403)
        self.assertEqual(self.client.get('/hosting/v1/apps/mate/deployments', **self.bearer(raw)).status_code, 403)
        self.assertEqual(
            self.client.post('/hosting/v1/apps/mate/deployments', {}, format='json', **self.bearer(raw)).status_code,
            403,
        )
        self.assertEqual(self.client.get('/hosting/v1/deploy-tokens', **self.bearer(raw)).status_code, 403)
        self.assertEqual(self.client.delete('/hosting/v1/apps/mate', **self.bearer(raw)).status_code, 403)

    def test_revoked_and_expired_and_invalid(self):
        token, raw = create_deploy_token(company_id=10, name='ci', created_by_id=1)
        rev = self.client.post(f'/hosting/v1/deploy-tokens/{token.id}/revoke', **self.owner())
        self.assertEqual(rev.status_code, 200)
        res = self.prepare(raw)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()['error'], 'deploy_token_revoked')
        self.assertNotIn(raw, res.content.decode())

        token2, raw2 = create_deploy_token(company_id=10, name='old', created_by_id=1, expires_in_days=1)
        DeployToken.objects.filter(id=token2.id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.prepare(raw2).json()['error'], 'deploy_token_expired')

        res = self.prepare('shellui_dt_nope')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()['error'], 'deploy_token_invalid')

    def test_revoke_is_company_scoped(self):
        token, _ = create_deploy_token(company_id=11, name='far', created_by_id=3)
        res = self.client.post(f'/hosting/v1/deploy-tokens/{token.id}/revoke', **self.owner())
        self.assertEqual(res.status_code, 404)
