"""Django admin sign-in still works with host-only session and CSRF cookies."""

from __future__ import annotations

import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

_HOST_COOKIES = {
    'SESSION_COOKIE_NAME': '__Host-sessionid',
    'CSRF_COOKIE_NAME': '__Host-csrftoken',
    'SESSION_COOKIE_SECURE': True,
    'CSRF_COOKIE_SECURE': True,
    'SESSION_COOKIE_HTTPONLY': True,
    'CSRF_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_DOMAIN': None,
    'CSRF_COOKIE_DOMAIN': None,
    'SESSION_COOKIE_PATH': '/',
    'CSRF_COOKIE_PATH': '/',
    'SESSION_COOKIE_SAMESITE': 'Lax',
    'CSRF_COOKIE_SAMESITE': 'Lax',
    'SECURE_SSL_REDIRECT': False,
}

_PLAIN_COOKIES = {
    'SESSION_COOKIE_NAME': 'sessionid',
    'CSRF_COOKIE_NAME': 'csrftoken',
    'SESSION_COOKIE_SECURE': False,
    'CSRF_COOKIE_SECURE': False,
    'SESSION_COOKIE_HTTPONLY': True,
    'CSRF_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_DOMAIN': None,
    'CSRF_COOKIE_DOMAIN': None,
    'SESSION_COOKIE_PATH': '/',
    'CSRF_COOKIE_PATH': '/',
    'SECURE_SSL_REDIRECT': False,
}

_PASSWORD = 'correct-horse-battery-staple'


def _csrf_token(html: str) -> str:
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    if not match:
        raise AssertionError('response did not include a CSRF token')
    return match.group(1)


def _assert_host_only(test, morsel, *, secure: bool):
    test.assertEqual(morsel['path'], '/')
    test.assertEqual(morsel['domain'], '')
    test.assertNotIn('domain=', morsel.OutputString().lower())
    test.assertTrue(morsel['httponly'])
    test.assertEqual(bool(morsel['secure']), secure)


class AdminLoginTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser('admin', 'admin@example.com', _PASSWORD)

    def _sign_in_and_out(self, *, secure: bool):
        client = Client(enforce_csrf_checks=True)
        extra = {'secure': secure}
        if secure:
            extra['HTTP_ORIGIN'] = 'https://testserver'
        login_page = client.get('/admin/login/', **extra)
        self.assertEqual(login_page.status_code, 200)
        csrf_cookie = login_page.cookies[settings.CSRF_COOKIE_NAME]
        _assert_host_only(self, csrf_cookie, secure=secure)
        self.assertEqual(csrf_cookie.key, settings.CSRF_COOKIE_NAME)

        posted = client.post(
            '/admin/login/',
            {
                'username': 'admin',
                'password': _PASSWORD,
                'csrfmiddlewaretoken': _csrf_token(login_page.content.decode()),
                'next': '/admin/',
            },
            **extra,
        )
        self.assertEqual(posted.status_code, 302, posted.content[:400])
        self.assertIn('/admin/', posted.url)
        session_cookie = posted.cookies[settings.SESSION_COOKIE_NAME]
        _assert_host_only(self, session_cookie, secure=secure)
        self.assertTrue(session_cookie.value)

        home = client.get('/admin/', **extra)
        self.assertEqual(home.status_code, 200)
        self.assertIn('_auth_user_id', client.session)
        self.assertContains(home, 'Log out')

        logged_out = client.post(
            '/admin/logout/',
            {'csrfmiddlewaretoken': _csrf_token(home.content.decode())},
            **extra,
        )
        self.assertIn(logged_out.status_code, (200, 302), logged_out.content[:400])
        if logged_out.status_code == 200:
            self.assertContains(logged_out, 'Logged out')
        self.assertNotIn('_auth_user_id', client.session)
        again = client.get('/admin/', **extra)
        self.assertEqual(again.status_code, 302)
        self.assertIn('/admin/login/', again.url)

    @override_settings(**_HOST_COOKIES)
    def test_admin_login_logout_with_host_prefixed_cookies(self):
        self.assertEqual(settings.SESSION_COOKIE_NAME, '__Host-sessionid')
        self.assertEqual(settings.CSRF_COOKIE_NAME, '__Host-csrftoken')
        self._sign_in_and_out(secure=True)

    @override_settings(**_PLAIN_COOKIES)
    def test_admin_login_logout_on_plain_http(self):
        self.assertEqual(settings.SESSION_COOKIE_NAME, 'sessionid')
        self.assertFalse(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self._sign_in_and_out(secure=False)
