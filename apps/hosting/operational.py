"""Custom domains, app-scoped environment variables, and operational log reads."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from apps.actions.emit import emit_event_if_rules

from .env_crypto import encrypt_env_value
from .hostname import normalize_hostname, validate_custom_hostname
from .models import App, AppCustomDomain, AppEnvironmentVariable, CustomDomainStatus, HostedAppRequestLog
from .services import HostingError, assert_hosting_access

_KEY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')


def _dns_verification_token(*, company_id: int, app_id: uuid.UUID, hostname: str) -> str:
    payload = f'{company_id}:{app_id}:{hostname.lower()}'
    digest = hashlib.sha256(
        (getattr(settings, 'SECRET_KEY', '') + payload + 'shellui-dns-verify-v1').encode()
    ).hexdigest()[:48]
    return f'shellui-domain-verify={digest}'


def _sanitize_path(path: str, *, max_len: int = 2048) -> str:
    raw = path or ''
    if len(raw) > max_len:
        return raw[: max_len - 3] + '...'
    return raw


def record_hosted_request(*, app: App, method: str, path: str, status_code: int, request_id: str = '') -> None:
    """Append one request log row and trim if over the configured cap."""
    max_rows = int(getattr(settings, 'HOSTING_REQUEST_LOG_MAX_PER_APP', 5000) or 5000)
    path_clean = _sanitize_path(path)
    HostedAppRequestLog.objects.create(
        app=app,
        method=(method or '')[:16],
        path=path_clean,
        status_code=min(max(int(status_code), 0), 65535),
        request_id=(request_id or '')[:128],
    )
    count = HostedAppRequestLog.objects.filter(app=app).count()
    if count <= max_rows:
        return
    overflow = count - max_rows
    if overflow <= 0:
        return
    batch = min(overflow + 50, 500)
    stale_ids = list(
        HostedAppRequestLog.objects.filter(app=app).order_by('created_at').values_list('id', flat=True)[:batch]
    )
    if stale_ids:
        HostedAppRequestLog.objects.filter(pk__in=stale_ids).delete()


def list_custom_domains(*, app: App) -> list[dict[str, Any]]:
    assert_hosting_access(app.company_id)
    rows = list(app.custom_domains.order_by('hostname'))
    company_id = app.company_id
    return [_serialize_custom_domain(row, company_id=company_id) for row in rows]


def get_custom_domain(*, app: App, domain_id: uuid.UUID) -> dict[str, Any]:
    assert_hosting_access(app.company_id)
    row = app.custom_domains.filter(id=domain_id).first()
    if row is None:
        raise HostingError('Custom domain not found.', status=404, code='custom_domain_not_found')
    return _serialize_custom_domain(row, company_id=app.company_id)


def add_custom_domain(
    *,
    app: App,
    hostname: str,
    user_id: int | None,
    actor_email: str = '',
) -> dict[str, Any]:
    assert_hosting_access(app.company_id)
    err = validate_custom_hostname(hostname)
    if err:
        raise HostingError(err, status=400, code='invalid_hostname')
    host = normalize_hostname(hostname)
    if AppCustomDomain.objects.filter(hostname=host).exists():
        raise HostingError(
            'This hostname is already registered for a hosted app.',
            status=409,
            code='duplicate_hostname',
        )
    row = AppCustomDomain.objects.create(app=app, hostname=host, status=CustomDomainStatus.PENDING_DNS)
    emit_event_if_rules(
        'hosting.custom_domain.created',
        app.company_id,
        _domain_event_payload(app, row),
        actor=_actor(user_id, actor_email),
    )
    return _serialize_custom_domain(row, company_id=app.company_id)


def refresh_custom_domain(*, app: App, domain_id: uuid.UUID) -> dict[str, Any]:
    row = app.custom_domains.filter(id=domain_id).first()
    if row is None:
        raise HostingError('Custom domain not found.', status=404, code='custom_domain_not_found')
    assert_hosting_access(app.company_id)
    # Honest contract: platform edge is not integrated; status advances only to awaiting_platform.
    if row.status == CustomDomainStatus.PENDING_DNS:
        row.status = CustomDomainStatus.AWAITING_PLATFORM
        row.save(update_fields=['status', 'updated_at'])
    emit_event_if_rules(
        'hosting.custom_domain.updated',
        app.company_id,
        _domain_event_payload(app, row),
    )
    return _serialize_custom_domain(row, company_id=app.company_id)


def remove_custom_domain(
    *,
    app: App,
    domain_id: uuid.UUID,
    user_id: int | None,
    actor_email: str = '',
) -> None:
    row = app.custom_domains.filter(id=domain_id).first()
    if row is None:
        raise HostingError('Custom domain not found.', status=404, code='custom_domain_not_found')
    assert_hosting_access(app.company_id)
    payload = _domain_event_payload(app, row)
    row.delete()
    emit_event_if_rules(
        'hosting.custom_domain.deleted',
        app.company_id,
        payload,
        actor=_actor(user_id, actor_email),
    )


def _serialize_custom_domain(row: AppCustomDomain, *, company_id: int) -> dict[str, Any]:
    app = row.app
    token = _dns_verification_token(company_id=company_id, app_id=app.id, hostname=row.hostname)
    return {
        'id': str(row.id),
        'app_id': str(app.id),
        'hostname': row.hostname,
        'status': row.status,
        'verified': False,
        'serving': False,
        'dns': {
            'verification_txt_name': f'_shellui.{row.hostname}',
            'verification_txt_value': token,
        },
        'instructions': _domain_instructions(row),
        'created_at': row.created_at.isoformat().replace('+00:00', 'Z'),
        'updated_at': row.updated_at.isoformat().replace('+00:00', 'Z'),
    }


def _domain_instructions(row: AppCustomDomain) -> str:
    app_domain = (getattr(settings, 'HOSTING_APP_DOMAIN', '') or '').strip()
    target = f'{row.app.slug}.{app_domain}' if app_domain else f'`<app-slug>.<HOSTING_APP_DOMAIN>`'
    lines = [
        'Add a CNAME from your hostname to the default app host '
        f'({target}).',
        'Add a TXT record at the `verification_txt_name` from this response with the `verification_txt_value`.',
        'This service does not terminate TLS or route traffic for custom hostnames yet. '
        'Status stays `awaiting_platform` until platform DNS and the edge are wired. '
        '`verified` and `serving` stay false until the backend confirms provisioning.',
    ]
    return ' '.join(lines)


def _actor(user_id: int | None, email: str = '') -> dict | None:
    if user_id is None:
        return None
    actor: dict = {'user_id': user_id}
    if email:
        actor['email'] = email
    return actor


def _domain_event_payload(app: App, row: AppCustomDomain) -> dict[str, Any]:
    return {
        'app_id': str(app.id),
        'domain_id': str(row.id),
        'hostname': row.hostname,
        'status': row.status,
    }


def list_env_variables(*, app: App) -> list[dict[str, Any]]:
    assert_hosting_access(app.company_id)
    rows = app.environment_variables.order_by('key')
    return [{'key': r.key, 'value_present': True, 'updated_at': r.updated_at.isoformat().replace('+00:00', 'Z')} for r in rows]


def get_env_variable(*, app: App, key: str) -> dict[str, Any]:
    assert_hosting_access(app.company_id)
    row = app.environment_variables.filter(key=key).first()
    if row is None:
        raise HostingError('Environment variable not found.', status=404, code='env_not_found')
    return {'key': row.key, 'value_present': True, 'updated_at': row.updated_at.isoformat().replace('+00:00', 'Z')}


def set_env_variable(
    *,
    app: App,
    key: str,
    value: str,
    user_id: int | None,
    actor_email: str = '',
) -> dict[str, Any]:
    assert_hosting_access(app.company_id)
    k = _validate_env_key(key)
    if value is None:
        raise HostingError('Value is required.', status=400, code='validation_failed')
    ciphertext = encrypt_env_value(str(value))
    with transaction.atomic():
        row, created = AppEnvironmentVariable.objects.update_or_create(
            app=app,
            key=k,
            defaults={'value_ciphertext': ciphertext},
        )
    action = 'hosting.environment_variable.created' if created else 'hosting.environment_variable.updated'
    emit_event_if_rules(
        action,
        app.company_id,
        {'app_id': str(app.id), 'key': k},
        actor=_actor(user_id, actor_email),
    )
    return {'key': row.key, 'value_present': True, 'updated_at': row.updated_at.isoformat().replace('+00:00', 'Z')}


def delete_env_variable(
    *,
    app: App,
    key: str,
    user_id: int | None,
    actor_email: str = '',
) -> None:
    assert_hosting_access(app.company_id)
    k = _validate_env_key(key)
    deleted, _ = app.environment_variables.filter(key=k).delete()
    if not deleted:
        raise HostingError('Environment variable not found.', status=404, code='env_not_found')
    emit_event_if_rules(
        'hosting.environment_variable.deleted',
        app.company_id,
        {'app_id': str(app.id), 'key': k},
        actor=_actor(user_id, actor_email),
    )


def _validate_env_key(key: str) -> str:
    k = (key or '').strip()
    if not k or not _KEY_RE.match(k):
        raise HostingError(
            'Key must match /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.',
            status=400,
            code='invalid_env_key',
        )
    return k


def list_app_runtime_logs(*, app: App, limit: int) -> dict[str, Any]:
    """
    Runtime logs are not collected in this deployment (static hosting only).

    Returns an explicit `unavailable` contract so agents never receive fake lines.
    """
    assert_hosting_access(app.company_id)
    cap = min(max(limit, 1), int(getattr(settings, 'HOSTING_RUNTIME_LOG_MAX_LINES', 500) or 500))
    return {
        'source': 'none',
        'unavailable_reason': (
            'Runtime process logs are not collected for static Shellui hosting in this release. '
            'Use request logs for HTTP visibility.'
        ),
        'lines': [],
        'truncated': False,
        'limit': cap,
    }


def list_app_request_logs(*, app: App, limit: int, cursor: str | None, status_min: int | None, status_max: int | None):
    assert_hosting_access(app.company_id)
    cap = min(max(limit, 1), int(getattr(settings, 'HOSTING_REQUEST_LOG_PAGE_MAX', 200) or 200))
    qs = HostedAppRequestLog.objects.filter(app=app).order_by('-created_at', '-id')
    if status_min is not None:
        qs = qs.filter(status_code__gte=status_min)
    if status_max is not None:
        qs = qs.filter(status_code__lte=status_max)
    if cursor:
        try:
            cursor_id = int(cursor)
        except ValueError:
            raise HostingError('cursor must be a numeric id from a previous page.', status=400, code='invalid_cursor')
        qs = qs.filter(Q(id__lt=cursor_id))
    rows = list(qs[: cap + 1])
    truncated = len(rows) > cap
    rows = rows[:cap]
    next_cursor = str(rows[-1].id) if truncated and rows else None
    return {
        'results': [
            {
                'id': r.id,
                'created_at': r.created_at.isoformat().replace('+00:00', 'Z'),
                'method': r.method,
                'path': r.path,
                'status_code': r.status_code,
                'request_id': r.request_id or None,
            }
            for r in rows
        ],
        'next_cursor': next_cursor,
        'limit': cap,
    }
