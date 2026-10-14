"""Hosted app responses cannot set cookies that reach other hosts."""

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.hosting.middleware import (
    HostedAppCookieScopeMiddleware,
    HostedAppNavigationPolicyMiddleware,
    strip_parent_domain_cookies,
)


def _response_with_cookies():
    response = HttpResponse('ok')
    response.set_cookie('planted', 'evil', domain='shellui.app', path='/')
    response.set_cookie('local', 'ok', path='/')
    response['Set-Cookie'] = 'raw=1; Domain=shellui.app; Path=/'
    return response


class HostedAppCookieScopeTests(SimpleTestCase):
    def test_middleware_is_outermost(self):
        self.assertEqual(
            settings.MIDDLEWARE[0],
            'apps.hosting.middleware.HostedAppCookieScopeMiddleware',
        )

    def test_app_host_drops_domain_cookies_and_keeps_coop(self):
        def inner(_request):
            return _response_with_cookies()

        request = RequestFactory().get('/', HTTP_HOST='demo.shellui.app')
        response = HostedAppCookieScopeMiddleware(inner)(request)
        self.assertNotIn('planted', response.cookies)
        self.assertEqual(response.cookies['local'].value, 'ok')
        self.assertEqual(response.cookies['local']['domain'], '')
        raw = response.headers.get('Set-Cookie')
        self.assertTrue(raw is None or 'domain' not in raw.lower())

        def with_coop(request):
            response = inner(request)
            return HostedAppNavigationPolicyMiddleware(lambda _req: response)(request)

        wrapped = HostedAppCookieScopeMiddleware(with_coop)(request)
        self.assertEqual(wrapped['Cross-Origin-Opener-Policy'], 'unsafe-none')
        self.assertNotIn('planted', wrapped.cookies)

    def test_platform_host_keeps_domain_cookies(self):
        def inner(_request):
            return _response_with_cookies()

        request = RequestFactory().get('/', HTTP_HOST='testserver')
        response = HostedAppCookieScopeMiddleware(inner)(request)
        self.assertEqual(response.cookies['planted']['domain'], 'shellui.app')
        self.assertIn('Domain=shellui.app', response.headers['Set-Cookie'])

    def test_strip_helper_removes_only_domain_cookies(self):
        response = strip_parent_domain_cookies(_response_with_cookies())
        self.assertNotIn('planted', response.cookies)
        self.assertIn('local', response.cookies)
        self.assertNotIn('Set-Cookie', response.headers)
