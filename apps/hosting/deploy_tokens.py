"""Per-app deploy tokens for CI (`shellui_dt_...`). Raw tokens are never stored or logged."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions

from apps.authapi.principal import HostingPrincipal

from .models import App, DeployToken

TOKEN_PREFIX = 'shellui_dt_'
_LOOKUP_LEN = len(TOKEN_PREFIX) + 8
_TOUCH_EVERY = timedelta(minutes=1)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def create_deploy_token(
    *, app: App, name: str, created_by_id: int | None, expires_in_days: int | None = None
) -> tuple[DeployToken, str]:
    label = (name or '').strip()[:100]
    if not label:
        raise ValueError('Token name is required.')
    expires_at = None
    if expires_in_days is not None:
        if expires_in_days < 1 or expires_in_days > 366:
            raise ValueError('expires_in_days must be between 1 and 366.')
        expires_at = timezone.now() + timedelta(days=expires_in_days)
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = DeployToken.objects.create(
        app=app,
        company_id=app.company_id,
        name=label,
        prefix=raw[:_LOOKUP_LEN],
        token_hash=hash_token(raw),
        created_by_id=created_by_id,
        expires_at=expires_at,
    )
    return token, raw


def revoke_deploy_token(token: DeployToken) -> DeployToken:
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=['revoked_at'])
    return token


def serialize_deploy_token(token: DeployToken) -> dict:
    iso = lambda v: v.isoformat() if v else None  # noqa: E731
    return {
        'id': str(token.id),
        'app_id': str(token.app_id),
        'name': token.name,
        'prefix': token.prefix,
        'created_by_id': token.created_by_id,
        'created_at': iso(token.created_at),
        'last_used_at': iso(token.last_used_at),
        'expires_at': iso(token.expires_at),
        'revoked_at': iso(token.revoked_at),
    }


def _fail(message: str, code: str):
    # Message and code only: the raw token never reaches errors or logs.
    return exceptions.AuthenticationFailed({'statusCode': '401', 'error': code, 'message': message})


def resolve_deploy_token(raw: str) -> DeployToken:
    digest = hash_token(raw)
    candidates = DeployToken.objects.filter(prefix=raw[:_LOOKUP_LEN])
    match = next((t for t in candidates if hmac.compare_digest(t.token_hash, digest)), None)
    if match is None:
        raise _fail('Deploy token is invalid.', 'deploy_token_invalid')
    if match.revoked_at is not None:
        raise _fail('Deploy token was revoked. Create a new one in admin.', 'deploy_token_revoked')
    now = timezone.now()
    if match.expires_at is not None and match.expires_at <= now:
        raise _fail('Deploy token has expired. Create a new one in admin.', 'deploy_token_expired')
    if match.last_used_at is None or now - match.last_used_at > _TOUCH_EVERY:
        DeployToken.objects.filter(id=match.id).update(last_used_at=now)
    return match


class DeployTokenAuthentication(authentication.BaseAuthentication):
    """`Authorization: Bearer shellui_dt_...`. Other Bearer values fall through to JWT auth."""

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode('utf-8', 'replace')
        parts = header.split()
        if len(parts) != 2 or parts[0] != 'Bearer' or not parts[1].startswith(TOKEN_PREFIX):
            return None
        token = resolve_deploy_token(parts[1])
        principal = HostingPrincipal(
            user_id=token.created_by_id or 0,
            company_id=token.company_id,
            deploy_token_app_id=str(token.app_id),
        )
        return (principal, None)

    def authenticate_header(self, request):
        return 'Bearer'
