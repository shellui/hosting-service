"""Forward catalog events to email-service ``POST /api/v1/events``.

Settings and the request body follow the email-service integration contract:
``EMAIL_SERVICE_URL``, ``EMAIL_SERVICE_API_KEY``, and the ``/api/v1/events`` fields.
An empty API key means no forwarding.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from apps.actions.models import ActionOutbox
from apps.actions.secret_redaction import redact_secrets
from apps.actions.webhook_retry import is_permanent_http_status
from apps.actions.webhook_transport import WebhookHTTPError, post_webhook_url
from config.request_context import request_id_var

logger = logging.getLogger(__name__)

SERVICE_NAME = 'hosting'
EVENTS_PATH = '/api/v1/events'


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


def email_service_allow_private() -> bool:
    """Private and loopback email-service URLs need an explicit opt-in."""
    return bool(getattr(settings, 'EMAIL_SERVICE_ALLOW_PRIVATE', False))


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


def email_event_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Event data for email-service. Sign-in links, tokens, and secret-shaped fields are omitted."""
    cleaned = redact_secrets(payload or {})
    return cleaned if isinstance(cleaned, dict) else {}


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
    payload = json.dumps(body).encode('utf-8')
    try:
        result = post_webhook_url(
            url,
            body=payload,
            headers=headers,
            timeout=timeout,
            allow_private=email_service_allow_private(),
        )
    except WebhookHTTPError as exc:
        logger.warning(
            'email_service_delivery event_type=%s company_id=%s http_status=%s',
            body.get('event_type'),
            body.get('company_id'),
            exc.status,
        )
        message = redact_api_key(str(exc))
        if message.startswith('Webhook URL'):
            message = 'Email service URL' + message[len('Webhook URL'):]
        raise EmailDeliveryError(
            message,
            http_status=exc.status,
            response_excerpt=redact_api_key(exc.response_excerpt or ''),
            permanent=bool(exc.permanent) or email_status_is_permanent(exc.status),
            retry_after_seconds=exc.retry_after_seconds,
        ) from None
    except OSError:
        logger.warning(
            'email_service_delivery event_type=%s company_id=%s http_status=%s',
            body.get('event_type'),
            body.get('company_id'),
            None,
        )
        raise EmailDeliveryError('Email service request failed.') from None

    if 200 <= result.status < 300:
        logger.info(
            'email_service_delivery event_type=%s company_id=%s http_status=%s',
            body.get('event_type'),
            body.get('company_id'),
            result.status,
        )
        return result.status

    excerpt = redact_api_key((result.excerpt or '')[:512])
    retry_after = result.retry_after_seconds if result.status in (429, 503) else None
    logger.warning(
        'email_service_delivery event_type=%s company_id=%s http_status=%s',
        body.get('event_type'),
        body.get('company_id'),
        result.status,
    )
    raise EmailDeliveryError(
        f'Email service returned HTTP {result.status}',
        http_status=result.status,
        response_excerpt=excerpt,
        permanent=email_status_is_permanent(result.status),
        retry_after_seconds=retry_after,
    )


def _looks_like_email(value: str) -> bool:
    if not value or '@' not in value or any(ch.isspace() for ch in value):
        return False
    local, _, domain = value.partition('@')
    return bool(local and domain and '.' in domain and not domain.startswith('.') and not domain.endswith('.'))
