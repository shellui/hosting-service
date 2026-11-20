"""Startup error when hosted apps share a cookie parent with identity or admin."""

from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings

from apps.hosting.checks import (
    cookie_parent_hosts_required_in_production,
    shared_cookie_parent_error,
)
from apps.hosting.domain_scope import registrable_domain

_ISOLATED = {
    'HOSTING_APP_DOMAIN': 'shellui.app',
    'IDENTITY_SERVICE_URL': 'https://auth.shellui.com',
    'IDENTITY_JWKS_URL': 'https://auth.shellui.com/.well-known/jwks.json',
    'EMAIL_SERVICE_URL': 'https://email.shellui.com',
    'CSRF_TRUSTED_ORIGINS': ['https://admin.shellui.com', 'http://localhost:8002'],
    'CORS_ALLOWED_ORIGINS': ['https://admin.shellui.com'],
    'SHELLUI_WEBSITE_URL': 'https://shellui.com',
    'SHELLUI_DOCS_URL': 'https://docs.shellui.com',
    'SHELLUI_PLAYGROUND_URL': 'https://playground.shellui.com',
    'SHELLUI_GITHUB_URL': 'https://github.com/shellui',
    'SHELLUI_AI_URL': 'https://shellui.ai',
}


class RegistrableDomainTests(SimpleTestCase):
    def test_last_two_labels(self):
        self.assertEqual(registrable_domain('auth.shellui.app'), 'shellui.app')
        self.assertEqual(registrable_domain('shellui.com'), 'shellui.com')
        self.assertIsNone(registrable_domain('localhost'))
        self.assertIsNone(registrable_domain('127.0.0.1'))
        self.assertIsNone(registrable_domain(''))


class SharedCookieParentCheckTests(SimpleTestCase):
    @override_settings(
        **{
            **_ISOLATED,
            'HOSTING_COOKIE_PARENT_HOSTS': ['https://auth.shellui.app', 'https://admin.shellui.com'],
        }
    )
    def test_fails_when_a_listed_host_shares_the_cookie_parent(self):
        errors = shared_cookie_parent_error(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'hosting.E001')
        self.assertIn('shellui.app', errors[0].msg)
        self.assertIn('auth.shellui.app', errors[0].msg)
        self.assertNotIn('admin.shellui.com', errors[0].msg)
        self.assertIn('HOSTING_COOKIE_PARENT_HOSTS', errors[0].hint)

    @override_settings(**{**_ISOLATED, 'HOSTING_COOKIE_PARENT_HOSTS': ['https://auth.shellui.com']})
    def test_silent_when_listed_hosts_use_a_different_parent(self):
        self.assertEqual(shared_cookie_parent_error(None), [])

    @override_settings(**{**_ISOLATED, 'HOSTING_COOKIE_PARENT_HOSTS': []})
    def test_empty_list_does_not_fail_the_parent_comparison(self):
        self.assertEqual(shared_cookie_parent_error(None), [])

    @override_settings(
        **{
            **_ISOLATED,
            'HOSTING_APP_DOMAIN': 'shellui.com',
            'HOSTING_COOKIE_PARENT_HOSTS': ['admin.shellui.com', 'https://auth.shellui.app'],
        }
    )
    def test_fails_when_admin_host_shares_shellui_com(self):
        errors = shared_cookie_parent_error(None)
        self.assertEqual(len(errors), 1)
        self.assertIn('admin.shellui.com', errors[0].msg)
        self.assertNotIn('auth.shellui.app', errors[0].msg)

    @override_settings(
        HOSTING_APP_DOMAIN='shellui.local',
        HOSTING_COOKIE_PARENT_HOSTS=['http://localhost:8001', 'https://auth.shellui.com'],
    )
    def test_localhost_is_not_a_cookie_parent(self):
        self.assertEqual(shared_cookie_parent_error(None), [])

    @override_settings(DEBUG=False, HOSTING_COOKIE_PARENT_HOSTS=[])
    def test_production_requires_the_host_list(self):
        errors = cookie_parent_hosts_required_in_production(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'hosting.E002')

    @override_settings(DEBUG=True, HOSTING_COOKIE_PARENT_HOSTS=[])
    def test_debug_allows_an_empty_host_list(self):
        self.assertEqual(cookie_parent_hosts_required_in_production(None), [])

    @override_settings(
        **{
            **_ISOLATED,
            'HOSTING_COOKIE_PARENT_HOSTS': ['https://auth.shellui.app'],
        }
    )
    def test_check_is_registered(self):
        found = [item for item in run_checks() if item.id == 'hosting.E001']
        self.assertEqual(len(found), 1)
