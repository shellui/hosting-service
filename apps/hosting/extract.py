"""Extract deployment tar.gz artifacts for static serving."""

from __future__ import annotations

import logging
import tarfile
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .paths import normalize_relative_path
from .storage import artifact_key, build_storage_key, delete_extracted_prefix, extracted_prefix

logger = logging.getLogger(__name__)

_READ_CHUNK_SIZE = 64 * 1024


class ExtractError(Exception):
    """Raised when artifact extraction fails validation."""


def _safe_member_name(name: str) -> str | None:
    return normalize_relative_path(name or '')


def _extract_limits() -> tuple[int, int, int]:
    max_files = int(getattr(settings, 'HOSTING_MAX_EXTRACT_FILES', 5000))
    max_total_bytes = int(getattr(settings, 'HOSTING_MAX_EXTRACT_BYTES', 500 * 1024**2))
    max_file_bytes = int(
        getattr(settings, 'HOSTING_MAX_EXTRACT_FILE_BYTES', settings.HOSTING_MAX_UPLOAD_BYTES)
    )
    return max_files, max_total_bytes, max_file_bytes


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
    max_total_bytes: int,
    max_file_bytes: int,
) -> int:
    count = 0
    total_bytes = 0

    for member in tar.getmembers():
        if not member.isfile():
            continue
        rel = _safe_member_name(member.name)
        if not rel:
            continue

        if count >= max_files:
            raise ExtractError(f'Extracted file count exceeds maximum ({max_files}).')

        if member.size > max_file_bytes:
            raise ExtractError(
                f'Extracted file exceeds maximum size ({max_file_bytes} bytes).'
            )

        extracted = tar.extractfile(member)
        if extracted is None:
            continue

        content = _read_member_limited(extracted, max_file_bytes=max_file_bytes)
        next_total = total_bytes + len(content)
        if next_total > max_total_bytes:
            raise ExtractError(
                f'Total extracted size exceeds maximum ({max_total_bytes} bytes).'
            )

        dest = build_storage_key(f'{prefix}{rel}')
        if default_storage.exists(dest):
            default_storage.delete(dest)
        default_storage.save(dest, ContentFile(content))
        count += 1
        total_bytes = next_total

    return count


def extract_deployment_artifact(deployment) -> int:
    """
    Extract artifact.tar.gz into {storage_prefix}extracted/.
    Returns number of files extracted.
    """
    key = artifact_key(deployment)
    if not default_storage.exists(key):
        raise FileNotFoundError(f'Artifact not found: {key}')

    delete_extracted_prefix(deployment.storage_prefix)
    prefix = extracted_prefix(deployment)
    max_files, max_total_bytes, max_file_bytes = _extract_limits()

    with default_storage.open(key, 'rb') as stored:
        data = stored.read()

    if not data:
        return 0

    try:
        tar = tarfile.open(fileobj=BytesIO(data), mode='r:*')
    except tarfile.TarError as exc:
        logger.warning(
            'Deployment %s artifact is not a valid tar archive: %s',
            deployment.id,
            exc,
        )
        return 0

    try:
        with tar:
            return _extract_tar_members(
                tar,
                prefix=prefix,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
                max_file_bytes=max_file_bytes,
            )
    except ExtractError:
        delete_extracted_prefix(deployment.storage_prefix)
        raise
