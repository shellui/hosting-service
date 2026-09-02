"""Extract deployment tar.gz artifacts for static serving."""

from __future__ import annotations

import logging
import tarfile
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .storage import artifact_key, build_storage_key, delete_extracted_prefix, extracted_prefix

logger = logging.getLogger(__name__)


def _safe_member_name(name: str) -> str | None:
    normalized = (name or '').replace('\\', '/').lstrip('/')
    if not normalized or normalized.startswith('../') or '/../' in normalized:
        return None
    return normalized


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
    count = 0

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

    with tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = _safe_member_name(member.name)
            if not rel:
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            content = extracted.read()
            dest = build_storage_key(f'{prefix}{rel}')
            if default_storage.exists(dest):
                default_storage.delete(dest)
            default_storage.save(dest, ContentFile(content))
            count += 1

    return count
