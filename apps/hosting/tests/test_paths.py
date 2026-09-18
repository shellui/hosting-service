"""Unit tests for shared path validation helpers."""

from django.http import Http404
from django.test import SimpleTestCase

from apps.hosting.paths import normalize_relative_path, raw_path_has_traversal, validate_serve_path


class NormalizeRelativePathTests(SimpleTestCase):
    def test_accepts_nested_relative_paths(self):
        self.assertEqual(normalize_relative_path('assets/app.js'), 'assets/app.js')

    def test_rejects_traversal_components(self):
        self.assertIsNone(normalize_relative_path('../etc/passwd'))
        self.assertIsNone(normalize_relative_path('assets/../../secret'))


class ServePathValidationTests(SimpleTestCase):
    def test_allows_root_path(self):
        self.assertEqual(validate_serve_path(''), '')
        self.assertEqual(validate_serve_path('/'), '')

    def test_rejects_literal_dotdot(self):
        with self.assertRaises(Http404):
            validate_serve_path('../index.html')
        with self.assertRaises(Http404):
            validate_serve_path('assets/../../secret.js')

    def test_rejects_encoded_traversal(self):
        with self.assertRaises(Http404):
            validate_serve_path('%2e%2e/index.html')
        with self.assertRaises(Http404):
            validate_serve_path('assets/%2e%2e/secret.js')

    def test_raw_path_has_traversal_detects_encoded_segments(self):
        self.assertTrue(raw_path_has_traversal('assets/%2e%2e/secret.js'))
        self.assertFalse(raw_path_has_traversal('assets/app.js'))
