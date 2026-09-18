"""Tests for tar extract caps and member path validation."""

import io
import tarfile

from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from apps.hosting.extract import ExtractError, _safe_member_name, extract_deployment_artifact
from apps.hosting.models import AccessStatus, CompanyHostingAccess
from apps.hosting.paths import normalize_relative_path
from apps.hosting.services import (
    HostingError,
    create_app,
    create_deployment,
    finalize_deployment,
    upload_deployment_artifact,
)
from apps.hosting.storage import extracted_file_key


def _make_tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class SafeMemberNameTests(TestCase):
    def test_accepts_simple_relative_paths(self):
        self.assertEqual(_safe_member_name('index.html'), 'index.html')
        self.assertEqual(_safe_member_name('assets/app.js'), 'assets/app.js')

    def test_rejects_parent_directory_segments(self):
        for name in ('../secret.txt', 'foo/../../etc/passwd', '..', 'foo/..', 'foo/../bar'):
            self.assertIsNone(_safe_member_name(name), msg=name)

    def test_rejects_windows_absolute_paths(self):
        self.assertIsNone(_safe_member_name('C:\\Windows\\System32'))
        self.assertIsNone(_safe_member_name('C:/Windows/System32'))

    def test_normalizes_backslashes_and_leading_slashes(self):
        self.assertEqual(_safe_member_name('\\assets\\app.js'), 'assets/app.js')
        self.assertEqual(_safe_member_name('/index.html'), 'index.html')

    def test_normalize_relative_path_rejects_dotdot_before_normpath(self):
        self.assertIsNone(normalize_relative_path('foo/bar/../secret'))


@override_settings(
    HOSTING_DEBUG_OPEN=True,
    HOSTING_MAX_EXTRACT_FILES=3,
    HOSTING_MAX_EXTRACT_BYTES=100,
    HOSTING_MAX_EXTRACT_FILE_BYTES=50,
)
class ExtractLimitTests(TestCase):
    def setUp(self):
        CompanyHostingAccess.objects.create(company_id=1, status=AccessStatus.APPROVED)
        self.app = create_app(company_id=1, name='extract-demo', display_name='Extract Demo')

    def _deploy_tarball(self, tarball: bytes):
        deployment = create_deployment(
            app=self.app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=1,
        )
        upload_deployment_artifact(
            deployment=deployment,
            fileobj=io.BytesIO(tarball),
            content_length=len(tarball),
        )
        return deployment

    def test_rejects_too_many_members(self):
        tarball = _make_tarball({f'file{i}.txt': b'x' for i in range(4)})
        deployment = self._deploy_tarball(tarball)
        with self.assertRaises(ExtractError):
            extract_deployment_artifact(deployment)
        self.assertFalse(default_storage.exists(extracted_file_key(deployment, 'file0.txt')))

    def test_rejects_oversized_member(self):
        tarball = _make_tarball({'big.bin': b'x' * 51})
        deployment = self._deploy_tarball(tarball)
        with self.assertRaises(ExtractError):
            extract_deployment_artifact(deployment)
        self.assertFalse(default_storage.exists(extracted_file_key(deployment, 'big.bin')))

    def test_rejects_total_uncompressed_bytes(self):
        tarball = _make_tarball(
            {
                'a.txt': b'a' * 40,
                'b.txt': b'b' * 40,
                'c.txt': b'c' * 40,
            }
        )
        deployment = self._deploy_tarball(tarball)
        with self.assertRaises(ExtractError):
            extract_deployment_artifact(deployment)
        self.assertFalse(default_storage.exists(extracted_file_key(deployment, 'a.txt')))

    def test_skips_unsafe_member_names(self):
        tarball = _make_tarball(
            {
                '../escape.txt': b'bad',
                'safe.txt': b'ok',
            }
        )
        deployment = self._deploy_tarball(tarball)
        count = extract_deployment_artifact(deployment)
        self.assertEqual(count, 1)
        self.assertTrue(default_storage.exists(extracted_file_key(deployment, 'safe.txt')))
        self.assertFalse(default_storage.exists(extracted_file_key(deployment, '../escape.txt')))

    def test_finalize_surfaces_extract_error(self):
        tarball = _make_tarball({'big.bin': b'x' * 51})
        deployment = self._deploy_tarball(tarball)
        with self.assertRaises(HostingError) as ctx:
            finalize_deployment(deployment=deployment)
        self.assertEqual(ctx.exception.code, 'artifact_extract_failed')
