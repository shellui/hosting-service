"""Deployment artifact storage helpers."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO

from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import default_storage
from django.http import HttpRequest
from django.urls import reverse

ARTIFACT_CONTENT_TYPE = 'application/gzip'


def is_s3_backend() -> bool:
    return getattr(settings, 'HOSTING_BACKEND', 'filesystem') == 's3'


def build_storage_key(relative: str) -> str:
    prefix = getattr(settings, 'HOSTING_KEY_PREFIX', 'hosting').strip().strip('/')
    relative = relative.strip().strip('/')
    return f'{prefix}/{relative}' if prefix else relative


def artifact_key(deployment) -> str:
    return build_storage_key(f'{deployment.storage_prefix}artifact.tar.gz')


def extracted_prefix(deployment_or_prefix) -> str:
    if hasattr(deployment_or_prefix, 'storage_prefix'):
        prefix = deployment_or_prefix.storage_prefix
    else:
        prefix = str(deployment_or_prefix)
    return f'{prefix.rstrip("/")}/extracted/'


def extracted_file_key(deployment, relative_path: str) -> str:
    rel = (relative_path or '').lstrip('/')
    return build_storage_key(f'{extracted_prefix(deployment)}{rel}')


def delete_extracted_prefix(storage_prefix: str) -> None:
    normalized = build_storage_key(extracted_prefix(storage_prefix))
    if not is_s3_backend():
        _delete_filesystem_tree(normalized)
        return
    try:
        dirs, files = default_storage.listdir(normalized)
        for name in files:
            default_storage.delete(f'{normalized}/{name}')
        for name in dirs:
            delete_extracted_prefix(f'{storage_prefix.rstrip("/")}/extracted/{name}')
    except Exception:
        return


def _delete_filesystem_tree(normalized_key: str) -> None:
    location = getattr(default_storage, 'location', None)
    if not location:
        return
    from pathlib import Path

    root = Path(location)
    target = root / normalized_key
    if not target.exists():
        return
    for path in sorted(target.rglob('*'), reverse=True):
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            path.rmdir()
    if target.is_dir():
        target.rmdir()


def open_extracted_file(deployment, relative_path: str):
    """Open an extracted file in one storage round-trip (no exists-before-open).

    Returns ``None`` when the object is missing or is a directory. Prefer this
    over ``exists()`` + ``open()`` on S3 (that pattern costs an extra HEAD).
    """
    key = extracted_file_key(deployment, relative_path)
    try:
        return default_storage.open(key, 'rb')
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        # FileSystemStorage can open a directory path as a false positive.
        return None
    except OSError:
        return None


def extracted_index_exists(deployment) -> bool:
    return default_storage.exists(extracted_file_key(deployment, 'index.html'))


class ArtifactTooLarge(ValueError):
    pass


def save_artifact(key: str, fileobj: BinaryIO, *, max_bytes: int) -> int:
    """Stream ``fileobj`` to a temp file in chunks, then store it. Stops once over ``max_bytes``."""
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024**2) as tmp:
        while True:
            chunk = fileobj.read(1024**2)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ArtifactTooLarge(f'Artifact exceeds maximum upload size ({max_bytes} bytes).')
            tmp.write(chunk)
        tmp.seek(0)
        if default_storage.exists(key):
            default_storage.delete(key)
        default_storage.save(key, File(tmp))
    return size


def _s3_object_key(storage_key: str) -> str:
    from storages.utils import clean_name

    storage = default_storage
    return storage._normalize_name(clean_name(storage_key))


def presigned_artifact_put_url(storage_key: str, *, content_type: str, expires_in: int) -> str:
    """Return a time-limited PUT URL for ``storage_key`` when using the S3 backend."""
    if not is_s3_backend():
        raise RuntimeError('presigned_artifact_put_url requires HOSTING_BACKEND=s3')
    storage = default_storage
    name = _s3_object_key(storage_key)
    return storage.connection.meta.client.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': storage.bucket.name,
            'Key': name,
            'ContentType': content_type,
        },
        ExpiresIn=expires_in,
        HttpMethod='PUT',
    )


def build_artifact_upload_target(
    deployment,
    *,
    request: HttpRequest,
    expires_in: int,
) -> dict[str, Any]:
    """Describe how an agent uploads bytes without sending them through MCP JSON."""
    key = artifact_key(deployment)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    app_ref = deployment.app.slug or str(deployment.app_id)
    upload_path = reverse(
        'hosting-deployment-upload',
        kwargs={'app_ref': app_ref, 'deployment_id': deployment.id},
    )
    if is_s3_backend():
        upload_url = presigned_artifact_put_url(
            key,
            content_type=ARTIFACT_CONTENT_TYPE,
            expires_in=expires_in,
        )
        return {
            'upload_url': upload_url,
            'method': 'PUT',
            'headers': {'Content-Type': ARTIFACT_CONTENT_TYPE},
            'requires_bearer': False,
            'expires_at': expires_at.isoformat().replace('+00:00', 'Z'),
            'backend': 's3',
        }
    upload_url = request.build_absolute_uri(upload_path)
    return {
        'upload_url': upload_url,
        'method': 'PUT',
        'headers': {'Content-Type': ARTIFACT_CONTENT_TYPE},
        'requires_bearer': True,
        'expires_at': expires_at.isoformat().replace('+00:00', 'Z'),
        'backend': 'direct',
    }


def delete_artifact_prefix(prefix: str) -> None:
    normalized = build_storage_key(prefix)
    if not is_s3_backend():
        return
    # Best-effort cleanup for S3; filesystem artifacts are left on disk for now.
    try:
        dirs, files = default_storage.listdir(normalized)
        for name in files:
            default_storage.delete(f'{normalized}/{name}')
        for name in dirs:
            delete_artifact_prefix(f'{prefix.rstrip("/")}/{name}')
    except Exception:
        return
