"""Deployment artifact storage helpers."""

from __future__ import annotations

from typing import BinaryIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


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
    key = extracted_file_key(deployment, relative_path)
    if not default_storage.exists(key):
        return None
    try:
        return default_storage.open(key, 'rb')
    except IsADirectoryError:
        # FileSystemStorage.exists() is true for directories created by route folders.
        return None
    except OSError:
        return None


def extracted_index_exists(deployment) -> bool:
    return default_storage.exists(extracted_file_key(deployment, 'index.html'))


def save_artifact(key: str, fileobj: BinaryIO, *, max_bytes: int) -> int:
    data = fileobj.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f'Artifact exceeds maximum upload size ({max_bytes} bytes).')
    if default_storage.exists(key):
        default_storage.delete(key)
    default_storage.save(key, ContentFile(data))
    return len(data)


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
