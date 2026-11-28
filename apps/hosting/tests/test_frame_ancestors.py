"""Strict validation of HOSTING_FRAME_ANCESTORS."""

from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings

from apps.hosting.checks import (
    FrameAncestorsError,
    frame_ancestors_sources,
    frame_ancestors_value_is_safe,
    parse_frame_ancestors,
)

VALID = [
    "'self'",
    "'none'",
    'https://shellui.com',
    'https://app.shellui.com:8443',
    "'self' https://shellui.com https://admin.shellui.com",
    'https://shellui.com   https://admin.shellui.com',
]

INVALID = [
    ('star', '*'),
    ('bare scheme', 'https:'),
    ('bare http scheme', 'http:'),
    ('wildcard host', 'https://*.shellui.app'),
    ('wildcard apex', 'https://*'),
    ('wildcard inside', 'https://app.*.shellui.app'),
    ('bare wildcard host', '*.shellui.app'),
    ('comma list', 'https://a.shellui.com,https://b.shellui.com'),
    ('comma with space', "'self', https://shellui.com"),
    ('semicolon injects a directive', "https://shellui.com; script-src *"),
    ('none with self', "'none' 'self'"),
    ('none with origin', "'none' https://shellui.com"),
    ('origin then none', "https://shellui.com 'none'"),
    ('http origin', 'http://shellui.com'),
    ('origin with a path', 'https://shellui.com/app'),
    ('origin with a trailing slash', 'https://shellui.com/'),
    ('origin with a query', 'https://shellui.com?x=1'),
    ('origin with userinfo', 'https://user@shellui.com'),
    ('uppercase host', 'https://Shellui.com'),
    ('single label host', 'https://localhost'),
    ('ip host', 'https://127.0.0.1:99999'),
    ('bad port', 'https://shellui.com:0'),
    ('huge port', 'https://shellui.com:70000'),
    ('unquoted none', 'none'),
    ('unquoted self', 'self'),
    ('data scheme', 'data:'),
    ('blob scheme', 'blob:'),
    ('newline injection', "'self'\nscript-src *"),
    ('control char', "'self'\x00"),
    ('non-ascii host', 'https://shellui.cöm'),
    ('empty label', 'https://shellui..com'),
    ('underscore host', 'https://my_app.shellui.com'),
    ('empty', ''),
    ('spaces only', '   '),
]


class ParseFrameAncestorsTests(SimpleTestCase):
    def test_valid_values_are_accepted(self):
        for value in VALID:
            with self.subTest(value=value):
                self.assertTrue(parse_frame_ancestors(value))

    def test_every_invalid_value_is_refused(self):
        for label, value in INVALID:
            with self.subTest(label=label, value=value):
                with self.assertRaises(FrameAncestorsError):
                    parse_frame_ancestors(value)

    def test_sources_are_normalised_and_deduplicated(self):
        self.assertEqual(
            parse_frame_ancestors("'self'   https://shellui.com 'self'"),
            ["'self'", 'https://shellui.com'],
        )


class FrameAncestorsSettingTests(SimpleTestCase):
    @override_settings(HOSTING_FRAME_ANCESTORS='')
    def test_unset_means_no_header(self):
        self.assertIsNone(frame_ancestors_sources())
        self.assertEqual(frame_ancestors_value_is_safe(None), [])

    @override_settings(HOSTING_FRAME_ANCESTORS="'self' https://shellui.com")
    def test_a_valid_value_passes_the_check(self):
        self.assertEqual(frame_ancestors_sources(), "'self' https://shellui.com")
        self.assertEqual(frame_ancestors_value_is_safe(None), [])

    def test_an_invalid_value_fails_the_startup_check(self):
        for label, value in INVALID:
            if not value.strip():
                continue
            with self.subTest(label=label), override_settings(HOSTING_FRAME_ANCESTORS=value):
                errors = frame_ancestors_value_is_safe(None)
                self.assertEqual([error.id for error in errors], ['hosting.E003'])

    @override_settings(HOSTING_FRAME_ANCESTORS='https://*.shellui.app')
    def test_the_check_is_registered(self):
        found = [item for item in run_checks() if item.id == 'hosting.E003']
        self.assertEqual(len(found), 1)

    def test_an_invalid_value_never_widens_the_policy(self):
        for label, value in INVALID:
            if not value.strip():
                continue
            with self.subTest(label=label), override_settings(HOSTING_FRAME_ANCESTORS=value):
                self.assertEqual(frame_ancestors_sources(), "'none'")
