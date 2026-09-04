"""Integration tests for static app serving."""

import io
import tarfile

from django.test import Client, TestCase, override_settings

from apps.hosting.models import AccessStatus, CompanyHostingAccess
from apps.hosting.services import (
    create_app,
    create_deployment,
    finalize_deployment,
    upload_deployment_artifact,
)


def _make_site_tarball(
    *,
    index_html: str = '<html><body>hello</body></html>',
    spa_html: str = '<html><body>spa</body></html>',
    extra_files: dict[str, str] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        files = {
            'index.html': index_html,
            '404.html': spa_html,
            **(extra_files or {}),
        }
        for name, content in files.items():
            data = content.encode('utf-8')
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@override_settings(
    HOSTING_APP_DOMAIN='shellui.test',
    HOSTING_APP_SCHEME='http',
    HOSTING_DEBUG_OPEN=True,
    ALLOWED_HOSTS=['*'],
)
class ServeIntegrationTests(TestCase):
    def setUp(self):
        CompanyHostingAccess.objects.create(company_id=1, status=AccessStatus.APPROVED)
        self.app = create_app(company_id=1, name='serve-demo', display_name='Serve Demo')
        tarball = _make_site_tarball(
            extra_files={
                'settings/index.html': '<html><body>settings</body></html>',
                'assets/app.js': 'console.log(1)',
            }
        )
        deployment = create_deployment(
            app=self.app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=1,
        )
        upload_deployment_artifact(
            deployment=deployment,
            fileobj=io.BytesIO(tarball),
            content_length=len(tarball),
        )
        finalize_deployment(deployment=deployment)
        self.client = Client()
        self.app_host = f'{self.app.slug}.shellui.test'

    def _body(self, response) -> bytes:
        if hasattr(response, 'streaming_content'):
            return b''.join(response.streaming_content)
        return response.content

    def test_serve_root_index(self):
        response = self.client.get('/', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'hello', self._body(response))

    def test_serve_nested_path(self):
        response = self.client.get('/index.html', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'hello', self._body(response))

    def test_unknown_host_404(self):
        response = self.client.get('/', HTTP_HOST='missing.shellui.test')
        self.assertEqual(response.status_code, 404)

    def test_serve_on_any_domain(self):
        alt_host = f'{self.app.slug}.custom.example'
        response = self.client.get('/', HTTP_HOST=alt_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'hello', self._body(response))

    def test_directory_route_serves_index(self):
        response = self.client.get('/settings', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'settings', self._body(response))

    def test_spa_fallback_uses_404_html(self):
        response = self.client.get('/settings/profile', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'spa', self._body(response))

    def test_admin_path_serves_spa_on_app_host(self):
        """SPA routes like /admin must not hit Django admin on app subdomains."""
        response = self.client.get('/admin', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'spa', self._body(response))
        self.assertNotIn(b'Django administration', self._body(response))

    def test_admin_trailing_slash_serves_spa_on_app_host(self):
        response = self.client.get('/admin/', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'spa', self._body(response))
        self.assertNotIn(b'Django administration', self._body(response))

    def test_api_path_serves_spa_on_app_host(self):
        response = self.client.get('/api/docs/', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'spa', self._body(response))

    def test_missing_asset_is_hard_404(self):
        response = self.client.get('/assets/missing.js', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 404)

    def test_hosted_app_can_be_embedded_in_iframe(self):
        response = self.client.get('/', HTTP_HOST=self.app_host)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.get('X-Frame-Options'), 'DENY')
        self.assertNotEqual(response.get('X-Frame-Options'), 'SAMEORIGIN')
