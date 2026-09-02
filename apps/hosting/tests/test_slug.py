"""Tests for app name and public slug helpers."""

from django.test import SimpleTestCase

from apps.hosting.slug import generate_public_slug, validate_app_name, validate_slug


class AppNameTests(SimpleTestCase):
    def test_valid_name(self):
        self.assertEqual(validate_app_name('playground'), 'playground')

    def test_rejects_reserved_name(self):
        with self.assertRaises(ValueError):
            validate_app_name('admin')


class SlugValidationTests(SimpleTestCase):
    def test_valid_slug(self):
        self.assertEqual(validate_slug('my-app'), 'my-app')

    def test_normalizes_case(self):
        self.assertEqual(validate_slug('My-App'), 'my-app')

    def test_rejects_short_slug(self):
        with self.assertRaises(ValueError):
            validate_slug('ab')

    def test_rejects_invalid_characters(self):
        with self.assertRaises(ValueError):
            validate_slug('my_app')

    def test_rejects_reserved_slug(self):
        with self.assertRaises(ValueError):
            validate_slug('admin')


class PublicSlugGenerationTests(SimpleTestCase):
    def test_generates_unique_slug(self):
        seen: set[str] = set()

        def exists(value: str) -> bool:
            return value in seen

        slug = generate_public_slug(exists=exists)
        self.assertRegex(slug, r'^[a-z][a-z0-9]{11}$')
        seen.add(slug)
        slug2 = generate_public_slug(exists=exists)
        self.assertNotEqual(slug, slug2)
