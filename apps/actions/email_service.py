"""Forward catalog events to email-service ``POST /api/v1/events``.

Settings and the request body follow the email-service integration contract:
``EMAIL_SERVICE_URL``, ``EMAIL_SERVICE_API_KEY``, and the ``/api/v1/events`` fields.
An empty API key means no forwarding.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from django.conf import settings

from apps.actions.models import ActionOutbox
from apps.actions.webhook_retry import is_permanent_http_status, parse_retry_after_header
from config.request_context import request_id_var

logger = logging.getLogger(__name__)

SERVICE_NAME = 'hosting'
EVENTS_PATH = '/api/v1/events'

# Identity strips these before a webhook or an email post. Hosting webhooks keep
# the original payload (same as storage-service). Only the email body drops them.
_SENSITIVE_KEYS = frozenset({
    'magic_link',
    'magic_link_url',
    'token',
    'raw_token',
    'access_token',
    'refresh_token',
    'id_token',
    'sign_in_url',
    'sign_in_link',
    'signin_url',
    'signin_link',
})
_SIGN_IN_URL = re.compile(
    r'magic[-_]link|/sign-?in(?:[/?#]|$)|[?&#]token=',
    re.IGNORECASE,
)


class EmailDeliveryError(Exception):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        response_excerpt: str = '',
        permanent: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.response_excerpt = response_excerpt
        self.permanent = permanent
        self.retry_after_seconds = retry_after_seconds


def email_service_api_key() -> str:
    return str(getattr(settings, 'EMAIL_SERVICE_API_KEY', '') or '').strip()


def email_service_configured() -> bool:
    """True when a service key is set. The URL alone does not enable forwarding."""
    return bool(email_service_api_key())


def email_service_events_url() -> str:
    base = str(getattr(settings, 'EMAIL_SERVICE_URL', '') or '').strip().rstrip('/')
    if not base:
        base = 'https://email.shellui.com'
    return f'{base}{EVENTS_PATH}'


def redact_api_key(text: str) -> str:
    """Remove the service key from text that might be logged or stored."""
    key = email_service_api_key()
    if not key or not text or key not in text:
        return text
    return text.replace(key, '[redacted]')


def email_status_is_permanent(status: int | None) -> bool:
    """Same HTTP classes as Shellui Actions webhook delivery.

    2xx is handled before this runs. 404, 408, 409, 425, 429, other unlisted 4xx,
    and 5xx retry. 400, 401, 403, 405, 410, 413, and 422 do not.
    """
    return is_permanent_http_status(status)


def recipient_hints(actor: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Recipient hints from the acting user. ``user_id`` is omitted when absent."""
    if not actor:
        return []
    email = str(actor.get('email') or '').strip()
    if not _looks_like_email(email):
        return []
    hint: dict[str, Any] = {'email': email}
    user_id = actor.get('user_id')
    if isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0:
        hint['user_id'] = user_id
    return [hint]


def _sensitive_key(key: str) -> bool:
    name = str(key).strip().lower().replace('-', '_')
    return name in _SENSITIVE_KEYS or name.endswith('_token') or name.endswith('_tokens')


def _sensitive_string(value: str) -> bool:
    """True when a string is a sign-in URL or carries a token query parameter."""
    if '://' not in value:
        return False
    return _SIGN_IN_URL.search(value) is not None


def email_event_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Event data for email-service. Sign-in links and tokens are omitted."""
    return _without_secrets(payload or {})


def _without_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _sensitive_key(str(key)):
                continue
            kept = _without_secrets(item)
            if kept is _DROP:
                continue
            cleaned[str(key)] = kept
        return cleaned
    if isinstance(value, list):
        items = []
        for item in value:
            kept = _without_secrets(item)
            if kept is _DROP:
                continue
            items.append(kept)
        return items
    if isinstance(value, str) and _sensitive_string(value):
        return _DROP
    return value


class _Drop:
    """Sentinel for a string that must not appear in the email body."""


_DROP = _Drop()


def build_event_body(
    *,
    event_type: str,
    company_id: int,
    payload: dict[str, Any],
    actor: dict[str, Any] | None,
    idempotency_key: str,
) -> dict[str, Any]:
    """JSON body for ``POST /api/v1/events``. Language is omitted so the company rule can choose it."""
    return {
        'service': SERVICE_NAME,
        'event_type': event_type,
        'company_id': int(company_id),
        'idempotency_key': idempotency_key,
        'payload': email_event_payload(payload),
        'recipients': recipient_hints(actor),
    }


def enqueue_email_event(
    *,
    event_type: str,
    company_id: int,
    payload: dict[str, Any],
    actor: dict[str, Any] | None,
    idempotency_key: str,
) -> ActionOutbox | None:
    """Insert one email outbox row, or return None when email-service is not configured."""
    if not email_service_configured():
        return None
    body = build_event_body(
        event_type=event_type,
        company_id=company_id,
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    return ActionOutbox.objects.create(
        company_id=int(company_id),
        action_rule=None,
        event_type=event_type,
        envelope=body,
        delivery_kind=ActionOutbox.KIND_EMAIL,
    )


def post_email_event(body: dict[str, Any]) -> int:
    """POST a stored event body. Returns the HTTP status. Raises ``EmailDeliveryError`` on failure."""
    if not email_service_configured():
        raise EmailDeliveryError('Email service is not configured.', permanent=True)

    url = email_service_events_url()
    if not url.startswith(('https://', 'http://')):
        raise EmailDeliveryError('Email service URL is not http(s).', permanent=True)

    key = email_service_api_key()
    headers = {
        'Authorization': f'Bearer {key}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': 'shellui-hosting-email/1.0',
    }
    request_id = request_id_var.get()
    if request_id and request_id != '-':
        headers['X-Request-ID'] = request_id
    timeout = float(getattr(settings, 'ACTIONS_WEBHOOK_TIMEOUT_SECONDS', 5.0))
    try:
        response = requests.post(
            url,
            json=body,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException:
        logger.warning(
            'email_service_delivery event_type=%s company_id=%s http_status=%s',
            body.get('event_type'),
            body.get('company_id'),
            None,
        )
        raise EmailDeliveryError('Email service request failed.') from None

    if 200 <= response.status_code < 300:
        logger.info(
            'email_service_delivery event_type=%s company_id=%s http_status=%s',
            body.get('event_type'),
            body.get('company_id'),
            response.status_code,
        )
        return response.status_code

    excerpt = redact_api_key((response.text or '')[:512])
    retry_after = None
    if response.status_code in (429, 503):
        retry_after = parse_retry_after_header(response.headers.get('Retry-After'))
    logger.warning(
        'email_service_delivery event_type=%s company_id=%s http_status=%s',
        body.get('event_type'),
        body.get('company_id'),
        response.status_code,
    )
    raise EmailDeliveryError(
        f'Email service returned HTTP {response.status_code}',
        http_status=response.status_code,
        response_excerpt=excerpt,
        permanent=email_status_is_permanent(response.status_code),
        retry_after_seconds=retry_after,
    )


def _looks_like_email(value: str) -> bool:
    if not value or '@' not in value or any(ch.isspace() for ch in value):
        return False
    local, _, domain = value.partition('@')
    return bool(local and domain and '.' in domain and not domain.startswith('.') and not domain.endswith('.'))
