"""Tests for the apex `/` landing view."""

from django.test import Client, TestCase, override_settings


@override_settings(HOSTING_APP_DOMAIN='shellui.app', HOSTING_APP_SCHEME='https')
class RootViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_root_renders_home_when_redirect_unset(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')

    @override_settings(ROOT_REDIRECT_URL='https://shellui.com')
    def test_root_permanent_redirect_when_configured(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], 'https://shellui.com')

    @override_settings(
        ROOT_REDIRECT_URL='https://shellui.com',
        HOSTING_APP_DOMAIN='shellui.test',
        HOSTING_APP_SCHEME='http',
        ALLOWED_HOSTS=['*'],
    )
    def test_root_redirect_does_not_apply_to_app_hosts(self):
        # App hosts still go through AppServeView (404 when no deployment).
        response = self.client.get('/', HTTP_HOST='missing.shellui.test')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('Location', response)

    def test_django_admin_available_on_apex_host(self):
        response = self.client.get('/admin/')
        # Login redirect or admin page — not a hosted-app 404.
        self.assertIn(response.status_code, {200, 302})
        if response.status_code == 302:
            self.assertIn('/admin/', response['Location'])

    def test_root_landing_includes_product_links(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('https://shellui.com', body)
        self.assertIn('https://docs.shellui.com', body)
        self.assertIn('shellui.app', body)
        self.assertIn('https://shellui.ai', body)
        self.assertIn('Agents', body)
        self.assertIn('apple-touch-icon.png', body)
        self.assertIn('favicon-32x32.png', body)
        self.assertIn('/static/css/site.css', body)
        self.assertIn('© 2026 Shellui', body)
        self.assertIn('aria-label="Platform"', body)

    def test_root_landing_shows_deploy_ready_copy_and_logo(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_superuser('admin', 'a@b.co', 'test-pass-12345')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('logo-shellui-mark', body)
        self.assertIn('logo-shellui', body)
        self.assertIn('viewBox="0 0 1024 270"', body)
        self.assertIn('shellui login', body)
        self.assertIn('shellui deploy', body)
        self.assertIn('https://q8n4m2xk7wph.shellui.app/', body)
        self.assertIn('q8n4m2xk7wph', body)
        self.assertNotIn('soon', body.lower())

    def test_llms_txt_available_on_apex(self):
        response = self.client.get('/llms.txt')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response['Content-Type'])
        body = response.content.decode()
        self.assertIn('shellui.app', body)
        self.assertIn('shellui deploy', body)
        self.assertIn('Example CLI output', body)
        self.assertNotIn('Optimistic', body)



@override_settings(HOSTING_APP_DOMAIN='eu.shellui.test', HOSTING_APP_SCHEME='https')
class RootRegionTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_superuser('admin', 'a@b.co', 'test-pass-12345')

    def test_region_line_shown_when_configured(self):
        with self.settings(HOSTING_REGION='EU'):
            body = self.client.get('/').content.decode()
        self.assertIn('data-region="EU"', body)
        self.assertIn('Region:', body)
        self.assertIn('&lt;name&gt;.eu.shellui.test', body)
        self.assertIn('https://q8n4m2xk7wph.eu.shellui.test/', body)
        self.assertIn('*.eu.shellui.test', body)

    def test_region_line_hidden_when_unset(self):
        with self.settings(HOSTING_REGION=''):
            body = self.client.get('/').content.decode()
        self.assertNotIn('data-region', body)
        self.assertNotIn('Region:', body)
        self.assertIn('*.eu.shellui.test', body)
        self.assertNotIn('*.shellui.app', body)

    def test_llms_txt_uses_region_domain(self):
        with self.settings(HOSTING_REGION='EU'):
            body = self.client.get('/llms.txt').content.decode()
        self.assertIn('# eu.shellui.test', body)
        self.assertIn('Region: EU.', body)
        self.assertIn('https://eu.shellui.test/llms.txt', body)
        with self.settings(HOSTING_REGION=''):
            body = self.client.get('/llms.txt').content.decode()
        self.assertNotIn('Region:', body)
