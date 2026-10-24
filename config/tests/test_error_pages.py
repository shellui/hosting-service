import json
from html import unescape

from django.http import Http404
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.views import defaults

from config import errors

BROWSER_ACCEPT = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
API_URL = '/hosting/v1/apps'


def _without_request_id(body):
    body = dict(body)
    body.pop('request_id', None)
    return body


class ApiErrorsStayJsonTests(TestCase):
    def test_api_error_is_json_when_browser_asks_for_html(self):
        response = self.client.get(API_URL, HTTP_ACCEPT=BROWSER_ACCEPT)
        self.assertIn(response.status_code, (401, 403))
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        json.loads(response.content)
        self.assertNotIn(b'<html', response.content.lower())
        self.assertNotIn(b'Django REST framework', response.content)

    def test_api_error_json_body_unchanged_for_api_clients(self):
        html = self.client.get(API_URL, HTTP_ACCEPT=BROWSER_ACCEPT)
        api = self.client.get(API_URL, HTTP_ACCEPT='application/json')
        self.assertEqual(html.status_code, api.status_code)
        self.assertEqual(_without_request_id(json.loads(html.content)), _without_request_id(json.loads(api.content)))

    def test_unknown_api_url_returns_json_404(self):
        response = self.client.get('/hosting/v1/does-not-exist', HTTP_ACCEPT=BROWSER_ACCEPT)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        self.assertEqual(_without_request_id(json.loads(response.content)), {'detail': 'Not found.'})


    def test_unknown_api_v1_url_returns_json_404(self):
        response = self.client.get('/api/v1/does-not-exist', HTTP_ACCEPT=BROWSER_ACCEPT)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(_without_request_id(json.loads(response.content)), {'detail': 'Not found.'})


class BrowserErrorPageTests(TestCase):
    def test_unknown_page_returns_branded_html_404(self):
        response = self.client.get('/no-such-page/', HTTP_ACCEPT=BROWSER_ACCEPT)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response['Content-Type'].startswith('text/html'))
        content = unescape(response.content.decode())
        self.assertIn("This page doesn't exist", content)
        self.assertIn('Shellui Hosting', content)
        self.assertIn('href="/"', content)
        self.assertIn('css/site.css', content)
        self.assertNotIn('/no-such-page/', content)


class ServerErrorTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_500_page_renders_without_details(self):
        request = self.factory.get('/boom/?secret=abc')
        response = errors.server_error(request)
        self.assertEqual(response.status_code, 500)
        content = unescape(response.content.decode())
        self.assertIn('Something went wrong', content)
        for leaked in ('Traceback', 'secret', 'abc', '/boom/', 'Exception'):
            self.assertNotIn(leaked, content)

    def test_500_falls_back_to_plain_html_when_template_fails(self):
        from unittest import mock

        with mock.patch.object(errors.loader, 'render_to_string', side_effect=RuntimeError('db down')):
            response = errors.server_error(self.factory.get('/boom/'))
        self.assertEqual(response.status_code, 500)
        content = response.content.decode()
        self.assertIn('Something went wrong', content)
        self.assertNotIn('db down', content)

    def test_500_under_api_is_json(self):
        response = errors.server_error(self.factory.get('/api/v1/boom'))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(_without_request_id(json.loads(response.content)), {'detail': 'Server error.'})

    def test_400_and_403_handlers(self):
        self.assertEqual(errors.bad_request(self.factory.get('/x')).status_code, 400)
        self.assertIn("You can't open this page", unescape(errors.permission_denied(self.factory.get('/x')).content.decode()))

    def test_handlers_are_registered(self):
        from config import urls

        self.assertEqual(urls.handler400, 'config.errors.bad_request')
        self.assertEqual(urls.handler403, 'config.errors.permission_denied')
        self.assertEqual(urls.handler404, 'config.errors.page_not_found')
        self.assertEqual(urls.handler500, 'config.errors.server_error')


class CsrfFailureTests(TestCase):
    def test_csrf_failure_renders_branded_page(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post('/', {'username': 'x'}, HTTP_ACCEPT=BROWSER_ACCEPT)
        self.assertEqual(response.status_code, 403)
        content = unescape(response.content.decode())
        self.assertIn('This form has expired', content)
        self.assertNotIn('CSRF verification failed', content)

    def test_csrf_failure_under_api_is_json(self):
        response = errors.csrf_failure(RequestFactory().post('/api/v1/x'), reason='CSRF cookie not set.')
        self.assertEqual(response.status_code, 403)
        body = _without_request_id(json.loads(response.content))
        self.assertIn('CSRF', body['detail'])
        self.assertNotIn('cookie', body['detail'].lower())


class HostedSiteErrorsUnchangedTests(SimpleTestCase):
    """Customer hosts keep Django's default error responses, never the Shellui page."""

    def setUp(self):
        self.factory = RequestFactory()

    def _hosted(self, path='/missing.js'):
        return self.factory.get(path, HTTP_HOST='mysite.shellui.local', HTTP_ACCEPT=BROWSER_ACCEPT)

    def test_hosted_site_404_is_django_default(self):
        request = self._hosted()
        response = errors.page_not_found(request, Http404('File not found'))
        expected = defaults.page_not_found(self._hosted(), Http404('File not found'))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, expected.content)
        self.assertNotIn(b"This page doesn", response.content)

    def test_hosted_site_404_under_api_path_is_not_json(self):
        response = errors.page_not_found(self._hosted('/api/x'), Http404())
        self.assertFalse(response['Content-Type'].startswith('application/json'))

    def test_hosted_site_500_is_django_default(self):
        response = errors.server_error(self._hosted('/'))
        self.assertEqual(response.content, defaults.server_error(self._hosted('/')).content)
