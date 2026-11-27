"""Tests for tar extract caps and member path validation."""

import bz2
import gzip
import io
import lzma
import tarfile
import zlib
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from apps.hosting.extract import (
    MAX_HEADER_RECORD_BYTES,
    ExtractError,
    _GzipLimitedReader,
    _safe_member_name,
    extract_deployment_artifact,
)
from apps.hosting.models import AccessStatus, CompanyHostingAccess, DeploymentStatus
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

    @override_settings(HOSTING_MAX_EXTRACT_MEMBERS=3)
    def test_rejects_member_count_before_a_later_file(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            for i in range(3):
                info = tarfile.TarInfo(name=f'dir{i}')
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            payload = b'secret'
            info = tarfile.TarInfo(name='secret.txt')
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        deployment = self._deploy_tarball(buf.getvalue())
        with self.assertRaises(ExtractError):
            extract_deployment_artifact(deployment)
        self.assertFalse(default_storage.exists(extracted_file_key(deployment, 'secret.txt')))

    @override_settings(HOSTING_MAX_EXTRACT_BYTES=50, HOSTING_MAX_EXTRACT_FILE_BYTES=50)
    def test_does_not_read_a_member_past_the_byte_budget(self):
        calls: list[str] = []
        real = tarfile.TarFile.extractfile

        def spy(tar, member, *args, **kwargs):
            calls.append(getattr(member, 'name', ''))
            return real(tar, member, *args, **kwargs)

        tarball = _make_tarball({'a.txt': b'a' * 40, 'b.txt': b'b' * 40})
        deployment = self._deploy_tarball(tarball)
        with patch('tarfile.TarFile.extractfile', spy):
            with self.assertRaises(ExtractError):
                extract_deployment_artifact(deployment)
        self.assertEqual(calls, ['a.txt'])
        self.assertFalse(default_storage.exists(extracted_file_key(deployment, 'a.txt')))
        self.assertFalse(default_storage.exists(extracted_file_key(deployment, 'b.txt')))

    def test_finalize_surfaces_extract_error(self):
        tarball = _make_tarball({'big.bin': b'x' * 51})
        deployment = self._deploy_tarball(tarball)
        with self.assertRaises(HostingError) as ctx:
            finalize_deployment(deployment=deployment)
        self.assertEqual(ctx.exception.code, 'artifact_extract_failed')


def _tar_bytes(members, *, fmt=tarfile.PAX_FORMAT) -> bytes:
    """Build an uncompressed tar from ``(TarInfo, bytes | None)`` pairs."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=fmt) as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


def _file(name: str, data: bytes = b'x'):
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    return info, data


def _dir(name: str):
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.DIRTYPE
    return info, None


def _gz(raw: bytes) -> bytes:
    return gzip.compress(raw, compresslevel=9)


@override_settings(
    HOSTING_DEBUG_OPEN=True,
    HOSTING_MAX_EXTRACT_FILES=50,
    HOSTING_MAX_EXTRACT_MEMBERS=100,
    HOSTING_MAX_EXTRACT_BYTES=1_000_000,
    HOSTING_MAX_EXTRACT_FILE_BYTES=500_000,
)
class ExtractHardeningTests(TestCase):
    def setUp(self):
        CompanyHostingAccess.objects.create(company_id=1, status=AccessStatus.APPROVED)
        self.app = create_app(company_id=1, name='harden-demo', display_name='Harden Demo')

    def _deploy(self, payload: bytes):
        deployment = create_deployment(
            app=self.app, app_version='1.0.0', shellui_version='0.5.0', deployed_by_id=1
        )
        upload_deployment_artifact(
            deployment=deployment, fileobj=io.BytesIO(payload), content_length=len(payload)
        )
        return deployment

    def _stored(self, deployment, name: str) -> bool:
        return default_storage.exists(extracted_file_key(deployment, name))

    def _assert_rejected(self, payload: bytes, *, stored: tuple[str, ...] = ('index.html',)):
        deployment = self._deploy(payload)
        with self.assertRaises(ExtractError):
            extract_deployment_artifact(deployment)
        for name in stored:
            self.assertFalse(self._stored(deployment, name), f'{name} was left behind')
        return deployment

    def _assert_finalize_fails_cleanly(self, payload: bytes):
        deployment = self._deploy(payload)
        with self.assertRaises(HostingError) as ctx:
            finalize_deployment(deployment=deployment)
        self.assertEqual(ctx.exception.code, 'artifact_extract_failed')
        self.assertGreaterEqual(ctx.exception.status, 400)
        self.assertLess(ctx.exception.status, 500)
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, DeploymentStatus.FAILED)
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_deployment_id)

    # Decompression bombs

    def test_the_reader_stops_at_its_limit_without_expanding_the_rest(self):
        bomb = gzip.compress(b'\0' * 50_000_000, compresslevel=9)
        reader = _GzipLimitedReader(io.BytesIO(bomb), limit=200_000)
        with self.assertRaises(ExtractError):
            while reader.read(10240):
                pass
        self.assertLessEqual(reader.total, 200_000 + 10240)

    def test_a_zero_padded_bomb_after_the_tar_end_is_rejected(self):
        tar = _tar_bytes([_file('index.html', b'ok')])
        payload = _gz(tar + b'\0' * 20_000_000)
        self._assert_finalize_fails_cleanly(payload)

    def test_a_skipped_member_bomb_is_rejected_before_its_body_is_read(self):
        bomb = _tar_bytes([_file('../x.bin', b'\0' * 3_000_000), _file('index.html', b'ok')])
        self._assert_rejected(_gz(bomb))

    def test_skipped_members_count_toward_the_total_byte_cap(self):
        members = [_file(f'../skip{i}.bin', b'\0' * 400_000) for i in range(3)]
        members.append(_file('index.html', b'ok'))
        self._assert_rejected(_gz(_tar_bytes(members)))

    def test_skipped_link_members_count_toward_the_member_cap(self):
        members = []
        for i in range(101):
            info = tarfile.TarInfo(name=f'link{i}')
            info.type = tarfile.SYMTYPE
            info.linkname = 'index.html'
            members.append((info, None))
        members.append(_file('index.html', b'ok'))
        self._assert_rejected(_gz(_tar_bytes(members)))

    def test_a_chain_of_pax_headers_is_bounded(self):
        members = []
        for i in range(60):
            info, data = _file(f'dir/{i}.txt', b'x')
            info.pax_headers = {'comment': 'c' * 50_000}
            members.append((info, data))
        self._assert_rejected(_gz(_tar_bytes(members)), stored=('dir/0.txt',))

    def test_a_pax_header_over_the_cap_is_rejected(self):
        info, data = _file('index.html', b'ok')
        info.pax_headers = {'comment': 'c' * (MAX_HEADER_RECORD_BYTES + 10)}
        self._assert_rejected(_gz(_tar_bytes([(info, data)])))

    def test_a_pax_header_that_declares_a_huge_size_is_rejected_without_reading_it(self):
        header = tarfile.TarInfo(name='PaxHeader')
        header.type = tarfile.XHDTYPE
        header.size = 800_000_000
        raw = header.tobuf(tarfile.GNU_FORMAT) + b'x' * 1024
        self._assert_rejected(_gz(raw))

    def test_a_gnu_long_name_over_the_cap_is_rejected(self):
        info, data = _file('a/' + 'n' * (MAX_HEADER_RECORD_BYTES + 100), b'ok')
        self._assert_rejected(_gz(_tar_bytes([(info, data)], fmt=tarfile.GNU_FORMAT)))

    def test_a_gnu_long_name_headers_stay_small_and_work(self):
        info, data = _file('a/' + '/'.join(['n' * 60] * 6) + '/page.html', b'ok')
        deployment = self._deploy(_gz(_tar_bytes([(info, data), _file('index.html', b'ok')], fmt=tarfile.GNU_FORMAT)))
        self.assertEqual(extract_deployment_artifact(deployment), 2)

    def test_a_declared_negative_or_sparse_member_is_rejected(self):
        info = tarfile.TarInfo(name='sparse.bin')
        info.type = tarfile.GNUTYPE_SPARSE
        info.size = 10
        raw = info.tobuf(tarfile.GNU_FORMAT) + b'\0' * 1024
        self._assert_rejected(_gz(raw))

    # Only gzip

    def test_only_gzip_is_accepted(self):
        tar = _tar_bytes([_file('index.html', b'ok')])
        for label, payload in (
            ('plain tar', tar),
            ('bz2', bz2.compress(tar)),
            ('xz', lzma.compress(tar)),
            ('zlib', zlib.compress(tar)),
            ('zip header', b'PK\x03\x04' + b'\0' * 600),
            ('random', b'\x01\x02' * 600),
        ):
            with self.subTest(label=label):
                self._assert_rejected(payload)

    def test_zstd_magic_is_refused(self):
        self._assert_rejected(b'\x28\xb5\x2f\xfd' + b'\0' * 600)

    # Truncated and corrupt

    def test_a_truncated_archive_never_goes_active(self):
        good = _gz(_tar_bytes([_file('index.html', b'<html>' + b'x' * 20_000), _file('b.txt', b'b' * 20_000)]))
        for cut in (len(good) // 2, len(good) - 8, len(good) - 1, 12):
            with self.subTest(cut=cut):
                self._assert_finalize_fails_cleanly(good[:cut])

    def test_a_corrupt_gzip_checksum_never_goes_active(self):
        good = bytearray(_gz(_tar_bytes([_file('index.html', b'<html>ok')])))
        good[-6] ^= 0xFF
        self._assert_finalize_fails_cleanly(bytes(good))

    def test_corrupt_deflate_data_never_goes_active(self):
        good = bytearray(_gz(_tar_bytes([_file('index.html', b'<html>' + bytes(range(256)) * 40)])))
        good[len(good) // 2] ^= 0xFF
        self._assert_finalize_fails_cleanly(bytes(good))

    def test_a_tar_cut_at_a_member_boundary_without_an_end_marker_is_rejected(self):
        raw = _tar_bytes([_file('index.html', b'<html>ok')]).rstrip(b'\0')
        self._assert_finalize_fails_cleanly(_gz(raw))

    def test_a_tar_cut_inside_a_member_body_is_rejected(self):
        raw = _tar_bytes([_file('index.html', b'<html>' + b'x' * 5000)])
        self._assert_finalize_fails_cleanly(_gz(raw[: 512 + 2000]))

    def test_garbage_after_the_gzip_stream_is_rejected(self):
        good = _gz(_tar_bytes([_file('index.html', b'ok')]))
        self._assert_finalize_fails_cleanly(good + b'trailing-junk')

    def test_a_good_archive_with_zero_padding_after_the_gzip_stream_is_accepted(self):
        good = _gz(_tar_bytes([_file('index.html', b'ok')]))
        deployment = self._deploy(good + b'\0' * 100)
        self.assertEqual(extract_deployment_artifact(deployment), 1)

    def test_concatenated_gzip_members_are_read_as_one_stream(self):
        raw = _tar_bytes([_file('index.html', b'ok')])
        half = len(raw) // 2
        deployment = self._deploy(gzip.compress(raw[:half]) + gzip.compress(raw[half:]))
        self.assertEqual(extract_deployment_artifact(deployment), 1)

    def test_an_empty_or_unreadable_body_never_goes_active(self):
        for payload in (b'x', b'\x1f\x8b', _gz(b'')):
            with self.subTest(payload=payload[:4]):
                self._assert_finalize_fails_cleanly(payload)

    # Zero files

    def test_an_archive_with_no_servable_file_is_refused(self):
        symlink = tarfile.TarInfo(name='only-link')
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = 'x'
        for label, members in (
            ('empty tar', []),
            ('directories only', [_dir('assets/'), _dir('css/')]),
            ('links only', [(symlink, None)]),
            ('unsafe names only', [_file('../x.txt', b'x'), _file('/', b'x')]),
        ):
            with self.subTest(label=label):
                self._assert_finalize_fails_cleanly(_gz(_tar_bytes(members)))

    # Links, duplicates, conflicts

    def test_symlinks_and_hardlinks_are_never_extracted(self):
        sym = tarfile.TarInfo(name='secret-link')
        sym.type = tarfile.SYMTYPE
        sym.linkname = '/etc/passwd'
        hard = tarfile.TarInfo(name='hard-link')
        hard.type = tarfile.LNKTYPE
        hard.linkname = 'index.html'
        deployment = self._deploy(
            _gz(_tar_bytes([_file('index.html', b'<html>ok'), (sym, None), (hard, None)]))
        )
        self.assertEqual(extract_deployment_artifact(deployment), 1)
        self.assertTrue(self._stored(deployment, 'index.html'))
        self.assertFalse(self._stored(deployment, 'secret-link'))
        self.assertFalse(self._stored(deployment, 'hard-link'))

    def test_a_file_through_a_symlink_directory_is_not_written_elsewhere(self):
        sym = tarfile.TarInfo(name='assets')
        sym.type = tarfile.SYMTYPE
        sym.linkname = '../../outside'
        deployment = self._deploy(_gz(_tar_bytes([(sym, None), _file('assets/pwn.txt', b'x'), _file('index.html')])))
        extract_deployment_artifact(deployment)
        self.assertFalse(default_storage.exists('outside/pwn.txt'))

    def test_a_repeated_path_is_rejected(self):
        self._assert_finalize_fails_cleanly(
            _gz(_tar_bytes([_file('index.html', b'one'), _file('index.html', b'two')]))
        )

    def test_a_path_repeated_through_normalisation_is_rejected(self):
        self._assert_finalize_fails_cleanly(
            _gz(_tar_bytes([_file('a/b.txt', b'one'), _file('a/./b.txt', b'two')]))
        )

    def test_a_file_before_a_folder_of_the_same_name_is_rejected(self):
        self._assert_finalize_fails_cleanly(_gz(_tar_bytes([_file('a', b'file'), _file('a/b', b'inner')])))

    def test_a_folder_member_before_a_file_of_the_same_name_is_rejected(self):
        self._assert_finalize_fails_cleanly(_gz(_tar_bytes([_dir('a/'), _file('a', b'file')])))

    def test_a_file_inside_a_path_that_was_a_file_deeper_down_is_rejected(self):
        self._assert_finalize_fails_cleanly(
            _gz(_tar_bytes([_file('a/b', b'file'), _file('a/b/c', b'inner')]))
        )

    def test_a_storage_error_midway_is_an_extract_error_and_cleans_up(self):
        payload = _gz(_tar_bytes([_file('index.html', b'ok'), _file('b.txt', b'b'), _file('c.txt', b'c')]))
        deployment = self._deploy(payload)
        real_save = default_storage.save
        calls = {'n': 0}

        def flaky(name, content, *args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 2:
                raise OSError('disk full')
            return real_save(name, content, *args, **kwargs)

        with patch.object(default_storage, 'save', flaky):
            with self.assertRaises(ExtractError):
                extract_deployment_artifact(deployment)
        for name in ('index.html', 'b.txt', 'c.txt'):
            self.assertFalse(self._stored(deployment, name))

    def test_a_storage_error_marks_the_deployment_failed_not_uploading(self):
        payload = _gz(_tar_bytes([_file('index.html', b'ok'), _file('b.txt', b'b')]))
        deployment = self._deploy(payload)
        real_save = default_storage.save
        calls = {'n': 0}

        def flaky(name, content, *args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 2:
                raise OSError('disk full')
            return real_save(name, content, *args, **kwargs)

        with patch.object(default_storage, 'save', flaky):
            with self.assertRaises(HostingError) as ctx:
                finalize_deployment(deployment=deployment)
        self.assertEqual(ctx.exception.status, 400)
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, DeploymentStatus.FAILED)
        self.assertFalse(self._stored(deployment, 'index.html'))

    def test_a_failed_deployment_can_be_uploaded_again_and_activated(self):
        deployment = self._deploy(b'not an archive')
        with self.assertRaises(HostingError):
            finalize_deployment(deployment=deployment)
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, DeploymentStatus.FAILED)
        good = _gz(_tar_bytes([_file('index.html', b'<html>ok')]))
        upload_deployment_artifact(deployment=deployment, fileobj=io.BytesIO(good), content_length=len(good))
        finalize_deployment(deployment=deployment)
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, DeploymentStatus.ACTIVE)

    def test_a_valid_archive_still_extracts(self):
        payload = _gz(
            _tar_bytes(
                [_dir('assets/'), _file('index.html', b'<html>ok'), _file('assets/app.js', b'x=1'), _file('./css/a.css', b'a{}')]
            )
        )
        deployment = self._deploy(payload)
        self.assertEqual(extract_deployment_artifact(deployment), 3)
        for name in ('index.html', 'assets/app.js', 'css/a.css'):
            self.assertTrue(self._stored(deployment, name))
