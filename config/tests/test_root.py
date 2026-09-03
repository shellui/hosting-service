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
