"""Startup warning when hosted apps share a parent domain with a service URL."""

from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings

from apps.hosting.checks import warn_shared_hosting_parent_domain
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


class SharedParentDomainCheckTests(SimpleTestCase):
    @override_settings(
        **{
            **_ISOLATED,
            'IDENTITY_SERVICE_URL': 'https://auth.shellui.app',
            'IDENTITY_JWKS_URL': 'https://auth.shellui.app/.well-known/jwks.json',
        }
    )
    def test_warns_when_identity_shares_shellui_app(self):
        warnings = warn_shared_hosting_parent_domain(None)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, 'hosting.W001')
        self.assertIn('shellui.app', warnings[0].msg)
        self.assertIn('IDENTITY_SERVICE_URL', warnings[0].msg)
        self.assertIn('auth.shellui.app', warnings[0].msg)
        self.assertNotIn('shellui.com', warnings[0].msg)
        self.assertIn('shellui.com', warnings[0].hint)

    @override_settings(**_ISOLATED)
    def test_silent_when_apps_and_identity_use_different_registrable_domains(self):
        self.assertEqual(warn_shared_hosting_parent_domain(None), [])

    @override_settings(
        **{
            **_ISOLATED,
            'HOSTING_APP_DOMAIN': 'apps.shellui.app',
            'EMAIL_SERVICE_URL': 'https://email.shellui.app',
        }
    )
    def test_warns_when_a_subdomain_parent_matches_email(self):
        warnings = warn_shared_hosting_parent_domain(None)
        self.assertEqual(len(warnings), 1)
        self.assertIn('EMAIL_SERVICE_URL', warnings[0].msg)
        self.assertIn('shellui.app', warnings[0].msg)

    @override_settings(
        **{
            **_ISOLATED,
            'HOSTING_APP_DOMAIN': 'shellui.com',
            'IDENTITY_SERVICE_URL': 'https://auth.shellui.app',
            'IDENTITY_JWKS_URL': 'https://auth.shellui.app/.well-known/jwks.json',
        }
    )
    def test_warns_when_admin_origin_shares_shellui_com(self):
        warnings = warn_shared_hosting_parent_domain(None)
        self.assertEqual(len(warnings), 1)
        self.assertIn('CSRF_TRUSTED_ORIGINS', warnings[0].msg)
        self.assertIn('admin.shellui.com', warnings[0].msg)
        self.assertNotIn('auth.shellui.app', warnings[0].msg)

    @override_settings(
        HOSTING_APP_DOMAIN='shellui.local',
        IDENTITY_SERVICE_URL='http://localhost:8000',
        IDENTITY_JWKS_URL='http://127.0.0.1:8000/.well-known/jwks.json',
        EMAIL_SERVICE_URL='https://email.shellui.com',
        CSRF_TRUSTED_ORIGINS=['http://localhost:8002'],
        CORS_ALLOWED_ORIGINS=['http://localhost:4000'],
        SHELLUI_WEBSITE_URL='https://shellui.com',
        SHELLUI_DOCS_URL='https://docs.shellui.com',
        SHELLUI_PLAYGROUND_URL='https://playground.shellui.com',
        SHELLUI_GITHUB_URL='https://github.com/shellui',
        SHELLUI_AI_URL='https://shellui.ai',
    )
    def test_localhost_and_distinct_parents_are_silent(self):
        self.assertEqual(warn_shared_hosting_parent_domain(None), [])

    @override_settings(
        **{
            **_ISOLATED,
            'IDENTITY_SERVICE_URL': 'https://auth.shellui.app',
            'IDENTITY_JWKS_URL': 'https://auth.shellui.app/.well-known/jwks.json',
        }
    )
    def test_check_is_registered(self):
        found = [item for item in run_checks() if item.id == 'hosting.W001']
        self.assertEqual(len(found), 1)
