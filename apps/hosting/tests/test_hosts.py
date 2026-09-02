"""Tests for hostname → slug resolution."""

from django.test import SimpleTestCase

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
