"""HTTP retry classification and Retry-After parsing for webhook delivery."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime

# Dead on first failure (no outbox retry).
PERMANENT_HTTP_STATUSES = frozenset({400, 401, 403, 405, 410, 413, 422})

# Explicitly retryable 4xx (404 covers inactive n8n workflows and test URLs).
RETRYABLE_HTTP_STATUSES = frozenset({404, 408, 409, 425, 429})


def permanent_http_status(status: int) -> bool:
    """Return True when an HTTP status should mark the outbox row dead (no retry)."""
    if status >= 500:
        return False
    if status in PERMANENT_HTTP_STATUSES:
        return True
    if status in RETRYABLE_HTTP_STATUSES:
        return False
    if 400 <= status < 500:
        # Unknown 4xx: retry (same policy as identity/storage n8n integration).
        return False
    return False


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    """Parse Retry-After as delay seconds (integer or HTTP-date). Returns None if invalid."""
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        reference = now or datetime.now(tz=dt_timezone.utc)
        return max(0, int((dt - reference).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def next_attempt_delay_seconds(
    *,
    attempt_number: int,
    http_status: int | None,
    retry_after_seconds: int | None,
    default_backoff,
) -> int:
    """
    Seconds until the next delivery attempt.

    Honors Retry-After on 429/503 (capped at 3600). Otherwise uses exponential backoff.
    """
    cap = 3600
    if http_status in (429, 503) and retry_after_seconds is not None:
        return min(max(1, retry_after_seconds), cap)
    return min(max(1, default_backoff(attempt_number)), cap)
