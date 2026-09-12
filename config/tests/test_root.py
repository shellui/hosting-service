"""Tests for the apex `/` landing view."""

from django.test import Client, TestCase, override_settings


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


    def test_root_landing_shows_deploy_ready_copy_and_logo(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_superuser('admin', 'a@b.co', 'test-pass-12345')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('logo-shellui', body)
        self.assertIn('shellui login', body)
        self.assertIn('shellui deploy', body)
        self.assertIn('https://my-app.shellui.app', body)
        self.assertNotIn('soon', body.lower())

    def test_llms_txt_available_on_apex(self):
        response = self.client.get('/llms.txt')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response['Content-Type'])
        body = response.content.decode()
        self.assertIn('shellui.app', body)
        self.assertIn('shellui deploy', body)

