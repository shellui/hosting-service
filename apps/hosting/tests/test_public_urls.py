"""Tests for public URL building."""

from django.test import SimpleTestCase, override_settings

from apps.hosting.public_urls import build_app_url


class PublicUrlTests(SimpleTestCase):
    @override_settings(
        HOSTING_APP_DOMAIN='shellui.local',
        HOSTING_APP_SCHEME='http',
    )
    def test_local_subdomain(self):
        self.assertEqual(
            build_app_url('demo'),
            'http://demo.shellui.local/',
        )

    @override_settings(
        HOSTING_APP_DOMAIN='shellui.app',
        HOSTING_APP_SCHEME='https',
    )
    def test_production_subdomain(self):
        self.assertEqual(
            build_app_url('playground'),
            'https://playground.shellui.app/',
        )
