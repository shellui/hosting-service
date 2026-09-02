from django.test import SimpleTestCase

from apps.hosting.semver import SemVer, compare_versions


class SemVerTests(SimpleTestCase):
    def test_parse_with_v_prefix(self):
        self.assertEqual(SemVer.parse('v1.2.3'), SemVer(1, 2, 3))

    def test_compare_versions(self):
        self.assertEqual(compare_versions('1.0.0', '1.0.1'), -1)
        self.assertEqual(compare_versions('2.0.0', '1.9.9'), 1)

    def test_satisfies_open_range(self):
        version = SemVer.parse('1.5.0')
        self.assertTrue(version.satisfies(minimum='1.0.0'))

    def test_satisfies_closed_range(self):
        version = SemVer.parse('1.5.0')
        self.assertTrue(version.satisfies(minimum='1.0.0', maximum='2.0.0'))
        self.assertFalse(version.satisfies(minimum='1.0.0', maximum='1.4.9'))

    def test_rejects_invalid_version(self):
        with self.assertRaises(ValueError):
            SemVer.parse('not-a-version')
