"""Tests for hostname → slug resolution."""

from django.test import SimpleTestCase, override_settings

from apps.hosting.hosts import slug_from_host


class SlugFromHostTests(SimpleTestCase):
    def test_shellui_local(self):
        self.assertEqual(slug_from_host('demo.shellui.local'), 'demo')

    def test_shellui_app(self):
        self.assertEqual(slug_from_host('demo.shellui.app'), 'demo')

    def test_any_domain(self):
        self.assertEqual(slug_from_host('demo.example.com'), 'demo')

    def test_with_port(self):
        self.assertEqual(slug_from_host('demo.shellui.local:8002'), 'demo')

    def test_localhost_is_not_app(self):
        self.assertIsNone(slug_from_host('localhost'))
        self.assertIsNone(slug_from_host('localhost:8002'))

    def test_ip_is_not_app(self):
        self.assertIsNone(slug_from_host('127.0.0.1'))
        self.assertIsNone(slug_from_host('127.0.0.1:8002'))

    def test_reserved_infrastructure_labels(self):
        self.assertIsNone(slug_from_host('hosting.shellui.local'))
        self.assertIsNone(slug_from_host('api.shellui.local'))

    def test_missing_slug(self):
        self.assertIsNone(slug_from_host('shellui.local'))


@override_settings(HOSTING_APP_DOMAIN='eu.shellui.app')
class RegionAppDomainTests(SimpleTestCase):
    def test_apex_is_platform(self):
        self.assertIsNone(slug_from_host('eu.shellui.app'))
        self.assertIsNone(slug_from_host('EU.Shellui.App.:443'))

    def test_www_apex_is_platform(self):
        self.assertIsNone(slug_from_host('www.eu.shellui.app'))

    def test_app_under_region_domain(self):
        self.assertEqual(slug_from_host('foo.eu.shellui.app'), 'foo')
        self.assertEqual(slug_from_host('foo.eu.shellui.app:8002'), 'foo')

    def test_reserved_under_region_domain(self):
        self.assertIsNone(slug_from_host('api.eu.shellui.app'))
        self.assertIsNone(slug_from_host('admin.eu.shellui.app'))

    def test_custom_domain_unchanged(self):
        self.assertEqual(slug_from_host('demo.example.com'), 'demo')


@override_settings(HOSTING_APP_DOMAIN='shellui.app')
class TwoLabelAppDomainTests(SimpleTestCase):
    def test_apex_and_www(self):
        self.assertIsNone(slug_from_host('shellui.app'))
        self.assertIsNone(slug_from_host('www.shellui.app'))

    def test_app(self):
        self.assertEqual(slug_from_host('foo.shellui.app'), 'foo')
