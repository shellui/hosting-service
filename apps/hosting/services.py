"""Core hosting operations."""

from __future__ import annotations

import uuid
from typing import BinaryIO

from datetime import timedelta

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AccessStatus,
    App,
    CompanyHostingAccess,
    Deployment,
    DeploymentStatus,
)
from .semver import SemVer
from .slug import generate_public_slug, validate_app_name, validate_slug
from .extract import extract_deployment_artifact
from .public_urls import build_app_url
from .identity_redirects import (
    app_origin_for_sync,
    delete_hosting_oauth_redirect_origin,
    upsert_hosting_oauth_redirect,
)
from .storage import (
    artifact_key,
    build_storage_key,
    delete_artifact_prefix,
    delete_extracted_prefix,
    is_s3_backend,
    save_artifact,
    _delete_filesystem_tree,
)


class HostingError(Exception):
    def __init__(self, message: str, *, status: int = 400, code: str = 'hosting_error'):
        super().__init__(message)
        self.status = status
        self.code = code


def require_company_id(principal) -> int:
    company_id = getattr(principal, 'company_id', None)
    if company_id is None:
        raise HostingError('JWT is missing company_id.', status=403, code='missing_company')
    return int(company_id)


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace('+00:00', 'Z')


def serialize_access(record: CompanyHostingAccess | None, *, company_id: int) -> dict:
    if record is None:
        return {
            'company_id': company_id,
            'status': 'none',
            'requested_at': None,
            'requested_by_id': None,
            'reviewed_at': None,
            'reviewed_by_id': None,
            'notes': '',
        }
    return {
        'company_id': record.company_id,
        'status': record.status,
        'requested_at': _iso(record.requested_at),
        'requested_by_id': record.requested_by_id,
        'reviewed_at': _iso(record.reviewed_at),
        'reviewed_by_id': record.reviewed_by_id,
        'notes': record.notes or '',
    }


def get_access(company_id: int) -> CompanyHostingAccess | None:
    return CompanyHostingAccess.objects.filter(company_id=company_id).first()


def assert_hosting_access(company_id: int) -> None:
    if getattr(settings, 'HOSTING_DEBUG_OPEN', False):
        return
    record = get_access(company_id)
    if record is None or record.status != AccessStatus.APPROVED:
        raise HostingError(
            'Company does not have hosting access. Request access first.',
            status=403,
            code='hosting_access_denied',
        )


def request_access(*, company_id: int, user_id: int) -> CompanyHostingAccess:
    record, created = CompanyHostingAccess.objects.get_or_create(
        company_id=company_id,
        defaults={
            'status': AccessStatus.PENDING,
            'requested_by_id': user_id,
        },
    )
    if not created and record.status == AccessStatus.DENIED:
        record.status = AccessStatus.PENDING
        record.requested_by_id = user_id
        record.requested_at = timezone.now()
        record.reviewed_by_id = None
        record.reviewed_at = None
        record.save()
    return record


def update_access(
    *,
    company_id: int,
    status: str,
    reviewer_id: int,
    notes: str = '',
) -> CompanyHostingAccess:
    if status not in AccessStatus.values:
        raise HostingError(f'Invalid status: {status!r}', code='invalid_status')
    record, _ = CompanyHostingAccess.objects.get_or_create(
        company_id=company_id,
        defaults={'requested_by_id': reviewer_id},
    )
    record.status = status
    record.reviewed_by_id = reviewer_id
    record.reviewed_at = timezone.now()
    record.notes = notes or record.notes
    record.save()
    return record


def preview_expires_at():
    days = int(getattr(settings, 'HOSTING_PREVIEW_TTL_DAYS', 7) or 7)
    return timezone.now() + timedelta(days=max(days, 1))


def is_preview_expired(app: App) -> bool:
    if app.expires_at is None:
        return False
    return app.expires_at <= timezone.now()


def renew_preview_expiry(app: App) -> None:
    """Extend preview lifetime after a successful deploy."""
    if app.created_by_id is None:
        return
    app.expires_at = preview_expires_at()
    app.save(update_fields=['expires_at', 'updated_at'])


def renew_app_expiry(app: App) -> App:
    """Reset preview expiry (admin / manual extend). Only while the site is still active."""
    if app.created_by_id is None and app.expires_at is None:
        raise HostingError(
            'This app is not a preview site.',
            status=409,
            code='not_preview',
        )
    if is_preview_expired(app):
        raise HostingError(
            'This preview site has expired and its files were removed. Deploy again to create a new site.',
            status=409,
            code='preview_expired',
        )
    app.expires_at = preview_expires_at()
    app.save(update_fields=['expires_at', 'updated_at'])
    return app


def _active_app_count(company_id: int) -> int:
    now = timezone.now()
    return App.objects.filter(company_id=company_id).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()


def resolve_app_ref(app_ref: str, *, company_id: int | None = None) -> App:
    ref = (app_ref or '').strip()
    if not ref:
        raise HostingError('App reference is required.', status=404, code='app_not_found')
    query = App.objects.all()
    if company_id is not None:
        query = query.filter(company_id=company_id)
    try:
        parsed = uuid.UUID(ref)
    except ValueError:
        parsed = None
    if parsed is not None:
        app = query.filter(id=parsed).first()
    else:
        app = query.filter(name=ref).first()
        if app is None:
            app = query.filter(slug=ref).first()
    if app is None:
        raise HostingError('App not found.', status=404, code='app_not_found')
    return app


def resolve_preview_app(*, slug: str, company_id: int, user_id: int) -> App:
    normalized = validate_slug(slug)
    app = App.objects.filter(slug=normalized).first()
    if app is None:
        raise HostingError(
            f'Preview site {normalized!r} not found. '
            'Remove hosting.slug (and deprecated hosting.app) from config to create a new site, '
            'or pass a slug that already belongs to you.',
            status=404,
            code='preview_not_found',
        )
    if app.company_id != company_id:
        raise HostingError(
            'Preview site belongs to another company.',
            status=403,
            code='preview_forbidden',
        )
    if app.created_by_id is not None and app.created_by_id != user_id:
        raise HostingError(
            'Preview site belongs to another user.',
            status=403,
            code='preview_forbidden',
        )
    return app


def create_preview_app(
    *,
    company_id: int,
    user_id: int,
    display_name: str = '',
    access_token: str | None = None,
) -> App:
    assert_hosting_access(company_id)
    max_apps = settings.HOSTING_MAX_APPS_PER_COMPANY
    if _active_app_count(company_id) >= max_apps:
        raise HostingError(
            f'Company preview site limit reached ({max_apps}).',
            status=403,
            code='app_quota_exceeded',
        )
    public_slug = generate_public_slug(exists=lambda value: App.objects.filter(slug=value).exists())
    label = (display_name or '').strip() or public_slug
    app = App.objects.create(
        name=public_slug,
        slug=public_slug,
        company_id=company_id,
        created_by_id=user_id,
        display_name=label,
    )
    token = (access_token or '').strip() or None
    transaction.on_commit(lambda: upsert_hosting_oauth_redirect(app, access_token=token))
    return app


@transaction.atomic
def prepare_preview_deploy(
    *,
    company_id: int,
    user_id: int,
    slug: str | None,
    display_name: str,
    app_version: str,
    shellui_version: str,
    access_token: str | None = None,
) -> tuple[App, Deployment]:
    token = (access_token or '').strip() or None
    if slug and slug.strip():
        app = resolve_preview_app(slug=slug.strip(), company_id=company_id, user_id=user_id)
        transaction.on_commit(lambda: upsert_hosting_oauth_redirect(app, access_token=token))
    else:
        app = create_preview_app(
            company_id=company_id,
            user_id=user_id,
            display_name=display_name,
            access_token=token,
        )
    deployment = create_deployment(
        app=app,
        app_version=app_version,
        shellui_version=shellui_version,
        deployed_by_id=user_id,
    )
    return app, deployment


def serialize_app(app: App) -> dict:
    payload = {
        'id': str(app.id),
        'name': app.name,
        'slug': app.slug,
        'company_id': app.company_id,
        'display_name': app.display_name,
        'expires_at': _iso(app.expires_at),
        'current_deployment_id': str(app.current_deployment_id) if app.current_deployment_id else None,
        'created_at': _iso(app.created_at),
        'updated_at': _iso(app.updated_at),
    }
    if app.current_deployment_id:
        try:
            payload['urls'] = {'url': build_app_url(app.slug)}
        except ValueError:
            pass
    return payload


def serialize_deployment(deployment: Deployment, *, app_slug: str | None = None) -> dict:
    slug = app_slug or deployment.app.slug
    payload = {
        'id': str(deployment.id),
        'app_id': str(deployment.app_id),
        'app_version': deployment.app_version,
        'shellui_version': deployment.shellui_version,
        'status': deployment.status,
        'pinned': deployment.pinned,
        'storage_prefix': deployment.storage_prefix,
        'deployed_by_id': deployment.deployed_by_id,
        'artifact_size': deployment.artifact_size,
        'created_at': _iso(deployment.created_at),
        'updated_at': _iso(deployment.updated_at),
        'finalized_at': _iso(deployment.finalized_at),
    }
    if deployment.app.current_deployment_id == deployment.id:
        try:
            payload['urls'] = {'url': build_app_url(slug)}
        except ValueError:
            payload['urls'] = {}
        payload['expires_at'] = _iso(deployment.app.expires_at)
    return payload


def create_app(
    *,
    company_id: int,
    name: str,
    display_name: str,
    access_token: str | None = None,
) -> App:
    assert_hosting_access(company_id)
    max_apps = settings.HOSTING_MAX_APPS_PER_COMPANY
    if App.objects.filter(company_id=company_id).count() >= max_apps:
        raise HostingError(
            f'Company app limit reached ({max_apps}).',
            status=403,
            code='app_quota_exceeded',
        )
    normalized_name = validate_app_name(name)
    if App.objects.filter(company_id=company_id, name=normalized_name).exists():
        raise HostingError(
            'App name already exists for this company.',
            status=409,
            code='app_name_taken',
        )
    public_slug = generate_public_slug(exists=lambda value: App.objects.filter(slug=value).exists())
    label = (display_name or '').strip() or normalized_name
    app = App.objects.create(
        name=normalized_name,
        slug=public_slug,
        company_id=company_id,
        display_name=label,
    )
    token = (access_token or '').strip() or None
    transaction.on_commit(lambda: upsert_hosting_oauth_redirect(app, access_token=token))
    return app


def create_deployment(
    *,
    app: App,
    app_version: str,
    shellui_version: str,
    deployed_by_id: int,
    pinned: bool = False,
) -> Deployment:
    assert_hosting_access(app.company_id)
    max_deployments = settings.HOSTING_MAX_DEPLOYMENTS_PER_APP
    if app.deployments.count() >= max_deployments:
        raise HostingError(
            f'Deployment limit reached for this app ({max_deployments}).',
            status=403,
            code='deployment_quota_exceeded',
        )
    SemVer.parse(app_version)
    SemVer.parse(shellui_version)
    deployment_id = uuid.uuid4()
    prefix = f'{app.id}/deployments/{deployment_id}/'
    return Deployment.objects.create(
        id=deployment_id,
        app=app,
        app_version=app_version.strip(),
        shellui_version=shellui_version.strip(),
        status=DeploymentStatus.DRAFT,
        pinned=pinned,
        storage_prefix=prefix,
        deployed_by_id=deployed_by_id,
    )


def upload_deployment_artifact(
    *,
    deployment: Deployment,
    fileobj: BinaryIO,
    content_length: int | None = None,
) -> Deployment:
    if deployment.status not in {DeploymentStatus.DRAFT, DeploymentStatus.UPLOADING, DeploymentStatus.FAILED}:
        raise HostingError(
            'Deployment cannot accept uploads in its current status.',
            status=409,
            code='invalid_deployment_status',
        )
    max_bytes = settings.HOSTING_MAX_UPLOAD_BYTES
    if content_length is not None and content_length > max_bytes:
        raise HostingError(
            f'Artifact exceeds maximum upload size ({max_bytes} bytes).',
            status=413,
            code='upload_too_large',
        )
    key = artifact_key(deployment)
    size = save_artifact(key, fileobj, max_bytes=max_bytes)
    deployment.status = DeploymentStatus.UPLOADING
    deployment.artifact_size = size
    deployment.save(update_fields=['status', 'artifact_size', 'updated_at'])
    return deployment


@transaction.atomic
def finalize_deployment(*, deployment: Deployment) -> Deployment:
    if deployment.status not in {DeploymentStatus.UPLOADING, DeploymentStatus.READY, DeploymentStatus.DRAFT}:
        raise HostingError(
            'Deployment cannot be finalized in its current status.',
            status=409,
            code='invalid_deployment_status',
        )
    if deployment.artifact_size <= 0:
        raise HostingError('Upload an artifact before finalizing.', code='artifact_missing')
    try:
        extract_deployment_artifact(deployment)
    except FileNotFoundError as exc:
        raise HostingError(str(exc), code='artifact_missing') from exc
    app = deployment.app
    now = timezone.now()
    Deployment.objects.filter(app=app, status=DeploymentStatus.ACTIVE).exclude(id=deployment.id).update(
        status=DeploymentStatus.SUPERSEDED,
        updated_at=now,
    )
    deployment.status = DeploymentStatus.ACTIVE
    deployment.finalized_at = now
    deployment.save(update_fields=['status', 'finalized_at', 'updated_at'])
    app.current_deployment = deployment
    renew_preview_expiry(app)
    app.save(update_fields=['current_deployment', 'updated_at'])
    return deployment


@transaction.atomic
def rollback_deployment(*, deployment: Deployment) -> Deployment:
    if deployment.status not in {
        DeploymentStatus.READY,
        DeploymentStatus.ACTIVE,
        DeploymentStatus.SUPERSEDED,
    }:
        raise HostingError(
            'Only ready or previously active deployments can be rolled back to.',
            status=409,
            code='invalid_deployment_status',
        )
    if deployment.artifact_size <= 0:
        raise HostingError('Deployment has no artifact.', code='artifact_missing')
    app = deployment.app
    now = timezone.now()
    Deployment.objects.filter(app=app, status=DeploymentStatus.ACTIVE).exclude(id=deployment.id).update(
        status=DeploymentStatus.SUPERSEDED,
        updated_at=now,
    )
    deployment.status = DeploymentStatus.ACTIVE
    deployment.finalized_at = deployment.finalized_at or now
    deployment.save(update_fields=['status', 'finalized_at', 'updated_at'])
    app.current_deployment = deployment
    app.save(update_fields=['current_deployment', 'updated_at'])
    return deployment


def delete_app_artifacts(app: App) -> None:
    for deployment in app.deployments.all():
        delete_extracted_prefix(deployment.storage_prefix)
        key = artifact_key(deployment)
        try:
            if default_storage.exists(key):
                default_storage.delete(key)
        except Exception:
            pass
        if is_s3_backend():
            delete_artifact_prefix(deployment.storage_prefix)
        else:
            _delete_filesystem_tree(build_storage_key(deployment.storage_prefix.rstrip('/')))


def delete_app(app: App, *, access_token: str | None = None) -> None:
    """Remove a hosted app, its deployments, and stored artifacts."""
    # Capture before delete; unsync after local removal so a failed delete does not
    # strip login while the site still exists.
    try:
        origin = app_origin_for_sync(app)
    except Exception:
        origin = None
    delete_app_artifacts(app)
    app.delete()
    if origin:
        delete_hosting_oauth_redirect_origin(origin=origin, access_token=access_token)
