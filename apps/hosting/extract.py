"""Extract deployment tar.gz artifacts for static serving.

The archive is untrusted. It is read as a gzip stream only (no bz2, xz or zstd), through a
reader that counts every decompressed byte against a hard limit, and the tar is opened in
``r|`` stream mode so one header is read at a time. Every member counts toward the caps,
whether it is extracted or skipped, and long-name headers (PAX and GNU) have a size cap.
Any failure to read the archive, truncated or corrupt data included, is an ``ExtractError``,
so a bad artifact never becomes ACTIVE.
"""

from __future__ import annotations

import logging
import tarfile
import zlib

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .paths import normalize_relative_path
from .storage import artifact_key, build_storage_key, delete_extracted_prefix, extracted_prefix

logger = logging.getLogger(__name__)

_READ_CHUNK_SIZE = 64 * 1024
_TAR_BLOCK = 512
# One PAX or GNU long-name header may carry at most this many bytes of record data.
MAX_HEADER_RECORD_BYTES = 64 * 1024
# Average header bytes allowed per member, in total across the archive (long names and PAX data).
_HEADER_BYTES_PER_MEMBER = 4096
# Header (512), padding (up to 511) and the end-of-archive blocks are not member data.
_FRAMING_BYTES_PER_MEMBER = 2 * _TAR_BLOCK
_GZIP_MAGIC = b'\x1f\x8b'


class ExtractError(Exception):
    """Raised when artifact extraction fails validation or the archive cannot be read."""


class _GzipLimitedReader:
    """Read a gzip stream with a hard limit on the total decompressed bytes.

    Decompresses at most what the caller asks for, so a bomb is never expanded in memory.
    Only gzip is accepted. A truncated stream, a bad checksum, bytes after the last member
    other than zero padding, and any other gzip fault raise ``ExtractError``.
    """

    def __init__(self, raw, *, limit: int):
        self._raw = raw
        self._limit = int(limit)
        self._pending = b''
        self._decoder = None
        self._eof = False
        self.total = 0
        self.tail = b''

    def _input(self) -> bytes:
        if self._pending:
            data, self._pending = self._pending, b''
            return data
        return self._raw.read(_READ_CHUNK_SIZE)

    def _start_member(self) -> bool:
        """Begin the next gzip member. False at a clean end of input."""
        while True:
            data = self._input()
            if not data:
                return False
            data = data.lstrip(b'\x00')
            if data:
                break
        while len(data) < len(_GZIP_MAGIC):
            more = self._raw.read(len(_GZIP_MAGIC) - len(data))
            if not more:
                break
            data += more
        if not data.startswith(_GZIP_MAGIC):
            raise ExtractError('The archive is not a gzip file.')
        self._decoder = zlib.decompressobj(wbits=31)
        self._pending = data
        return True

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = _READ_CHUNK_SIZE
        out = bytearray()
        try:
            while len(out) < size and not self._eof:
                if self._decoder is None and not self._start_member():
                    self._eof = True
                    break
                data = self._input()
                chunk = self._decoder.decompress(data, size - len(out))
                if self._decoder.eof:
                    self._pending = self._decoder.unused_data
                    self._decoder = None
                else:
                    self._pending = self._decoder.unconsumed_tail
                    if not data and not chunk:
                        raise ExtractError('The archive is truncated.')
                if chunk:
                    out += chunk
                    self.total += len(chunk)
                    if self.total > self._limit:
                        raise ExtractError(
                            f'The archive expands beyond the maximum size ({self._limit} bytes).'
                        )
        except ExtractError:
            raise
        except (zlib.error, EOFError, OSError, ValueError) as exc:
            raise ExtractError(f'The archive is not a valid gzip file: {exc}') from exc
        if out:
            self.tail = (self.tail + bytes(out))[-2 * _TAR_BLOCK :]
        return bytes(out)

    def finish(self) -> None:
        """Read to the end so the gzip checksum is verified, and require the tar end marker."""
        while self.read(_READ_CHUNK_SIZE):
            pass
        if self.total < 2 * _TAR_BLOCK or self.tail.strip(b'\x00'):
            raise ExtractError('The archive is truncated: the tar end marker is missing.')

    def close(self) -> None:
        self._pending = b''
        self._decoder = None


def _bounded_tarinfo(*, max_members: int):
    """A ``TarInfo`` that caps header records, refuses sparse members and bounds header bytes."""
    state = {'header_bytes': 0, 'headers': 0}
    header_budget = (max_members + 1) * _HEADER_BYTES_PER_MEMBER

    class BoundedTarInfo(tarfile.TarInfo):
        def _proc_member(self, tar):
            if self.type in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
                kind = 'GNU long-name'
            elif self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE):
                kind = 'PAX'
            elif self.type == tarfile.GNUTYPE_SPARSE:
                raise ExtractError('Sparse archive members are not supported.')
            else:
                kind = ''
            if kind:
                size = int(self.size or 0)
                if size < 0 or size > MAX_HEADER_RECORD_BYTES:
                    raise ExtractError(f'A {kind} header is larger than {MAX_HEADER_RECORD_BYTES} bytes.')
                state['header_bytes'] += size
                state['headers'] += 1
                if state['header_bytes'] > header_budget or state['headers'] > max_members + 1:
                    raise ExtractError('The archive has too much header data.')
            return super()._proc_member(tar)

    return BoundedTarInfo


def _safe_member_name(name: str) -> str | None:
    return normalize_relative_path(name or '')


def _extract_limits() -> tuple[int, int, int, int]:
    max_files = int(getattr(settings, 'HOSTING_MAX_EXTRACT_FILES', 5000))
    max_members = int(getattr(settings, 'HOSTING_MAX_EXTRACT_MEMBERS', 10000))
    max_total_bytes = int(getattr(settings, 'HOSTING_MAX_EXTRACT_BYTES', 500 * 1024**2))
    max_file_bytes = int(
        getattr(settings, 'HOSTING_MAX_EXTRACT_FILE_BYTES', settings.HOSTING_MAX_UPLOAD_BYTES)
    )
    return max_files, max_members, max_total_bytes, max_file_bytes


def _read_member_limited(extracted, *, max_file_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = extracted.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_file_bytes:
            raise ExtractError(
                f'Extracted file exceeds maximum size ({max_file_bytes} bytes).'
            )
        chunks.append(chunk)
    return b''.join(chunks)


def _extract_tar_members(
    tar: tarfile.TarFile,
    *,
    prefix: str,
    max_files: int,
    max_members: int,
    max_total_bytes: int,
    max_file_bytes: int,
) -> int:
    """Stream members. Caps are applied as each header is read, before its body.

    Every member counts toward the member and byte caps, extracted or not, so a body that is
    skipped (an unsafe name, a link, a device) cannot hide a bomb.
    """
    count = 0
    member_count = 0
    declared_bytes = 0
    files: set[str] = set()
    dirs: set[str] = set()

    for member in tar:
        member_count += 1
        if member_count > max_members:
            raise ExtractError(f'Archive member count exceeds maximum ({max_members}).')

        size = int(getattr(member, 'size', 0) or 0)
        if size < 0:
            raise ExtractError('The archive has a member with a negative size.')
        declared_bytes += size
        if declared_bytes > max_total_bytes:
            raise ExtractError(f'Total extracted size exceeds maximum ({max_total_bytes} bytes).')

        if member.issparse():
            raise ExtractError('Sparse archive members are not supported.')

        if member.isdir():
            rel_dir = _safe_member_name(member.name)
            if rel_dir:
                _register_dir(rel_dir, files=files, dirs=dirs)
            continue

        if not member.isfile():
            # Symlinks, hardlinks, devices and fifos are never extracted.
            continue

        rel = _safe_member_name(member.name)
        if not rel:
            continue

        if count >= max_files:
            raise ExtractError(f'Extracted file count exceeds maximum ({max_files}).')
        if size > max_file_bytes:
            raise ExtractError(f'Extracted file exceeds maximum size ({max_file_bytes} bytes).')
        _register_file(rel, files=files, dirs=dirs)

        extracted = tar.extractfile(member)
        if extracted is None:
            continue

        content = _read_member_limited(extracted, max_file_bytes=max_file_bytes)
        dest = build_storage_key(f'{prefix}{rel}')
        if default_storage.exists(dest):
            default_storage.delete(dest)
        default_storage.save(dest, ContentFile(content))
        count += 1

    return count


def _register_dir(rel: str, *, files: set[str], dirs: set[str]) -> None:
    rel = rel.rstrip('/')
    parts = rel.split('/')
    for i in range(1, len(parts) + 1):
        parent = '/'.join(parts[:i])
        if parent in files:
            raise ExtractError(f'The archive has both a file and a folder named {parent!r}.')
        dirs.add(parent)


def _register_file(rel: str, *, files: set[str], dirs: set[str]) -> None:
    """Reject a repeated path and any file and folder that share a name (``a`` and ``a/b``)."""
    if rel in files:
        raise ExtractError(f'The archive has the file {rel!r} more than once.')
    if rel in dirs:
        raise ExtractError(f'The archive has both a file and a folder named {rel!r}.')
    parts = rel.split('/')
    for i in range(1, len(parts)):
        parent = '/'.join(parts[:i])
        if parent in files:
            raise ExtractError(f'The archive has both a file and a folder named {parent!r}.')
        dirs.add(parent)
    files.add(rel)


def extract_deployment_artifact(deployment) -> int:
    """
    Extract artifact.tar.gz into {storage_prefix}extracted/.
    Returns the number of files extracted, always at least one.

    Raises ``FileNotFoundError`` when the artifact is missing, and ``ExtractError`` for every
    other failure: a bad, truncated or corrupt archive, a limit, a conflict, or a storage
    error while writing. Files written so far are removed before it raises.
    """
    key = artifact_key(deployment)
    if not default_storage.exists(key):
        raise FileNotFoundError(f'Artifact not found: {key}')

    delete_extracted_prefix(deployment.storage_prefix)
    prefix = extracted_prefix(deployment)
    max_files, max_members, max_total_bytes, max_file_bytes = _extract_limits()
    stream_limit = (
        max_total_bytes
        + (max_members + 1) * _FRAMING_BYTES_PER_MEMBER
        + (max_members + 1) * _HEADER_BYTES_PER_MEMBER
        + 2 * _TAR_BLOCK
    )

    try:
        with default_storage.open(key, 'rb') as stored:
            reader = _GzipLimitedReader(stored, limit=stream_limit)
            try:
                # r| reads one header at a time and does not buffer the archive.
                tar = tarfile.open(
                    fileobj=reader,
                    mode='r|',
                    tarinfo=_bounded_tarinfo(max_members=max_members),
                )
                with tar:
                    count = _extract_tar_members(
                        tar,
                        prefix=prefix,
                        max_files=max_files,
                        max_members=max_members,
                        max_total_bytes=max_total_bytes,
                        max_file_bytes=max_file_bytes,
                    )
                reader.finish()
            finally:
                reader.close()
        if count < 1:
            raise ExtractError('The archive has no files to serve.')
        return count
    except ExtractError:
        delete_extracted_prefix(deployment.storage_prefix)
        raise
    except Exception as exc:
        # Truncated or corrupt data, an odd header, a file and folder clash on the storage
        # backend, a write error. Never a 500 and never a half-written site.
        delete_extracted_prefix(deployment.storage_prefix)
        logger.warning(
            'Deployment %s artifact could not be extracted: %s: %s',
            deployment.id,
            type(exc).__name__,
            exc,
        )
        raise ExtractError(f'The artifact could not be extracted ({type(exc).__name__}).') from exc
