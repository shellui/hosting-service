---
description: Forward hosting events to email-service so a company rule can send mail. The email body omits sign-in links and tokens.
---

# Email notifications

hosting-service posts each catalog event to [email-service](https://github.com/shellui/email-service) when `EMAIL_SERVICE_API_KEY` is set. email-service sends mail only when that company has an enabled rule for the event. With the key unset, hosting-service does not call email-service.

[Shellui Actions](actions.md) webhooks are a separate path. A webhook rule does not send mail, and mail does not require a webhook rule. Webhook envelopes, signing, and retries stay the same as identity-service and storage-service.

## Events that are forwarded

hosting-service posts every catalog event it already emits. Catalog `default_enabled` does not send mail by itself. A company receives mail only after it creates a rule in email-service.

| Event type | Catalog default |
| --- | --- |
| `hosting.deployment.failed` | Enabled. Mail waits for a company rule |
| `hosting.app.created` | Disabled until the company creates a rule |
| `hosting.app.deleted` | Disabled until the company creates a rule |
| `hosting.deployment.created` | Disabled until the company creates a rule |
| `hosting.deployment.succeeded` | Disabled until the company creates a rule |

hosting-service does not store those rules.

## Configuration

Set both variables on the hosting-service process. Names match the [email-service integration contract](https://github.com/shellui/email-service/blob/main/docs/integration.md).

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMAIL_SERVICE_URL` | `https://email.shellui.com` | Origin only. hosting-service appends `/api/v1/events` |
| `EMAIL_SERVICE_API_KEY` | empty | Service key with prefix `esk_`. Sent as `Authorization: Bearer` |

Issue the key in email-service for service `hosting`, lane `transactional`, and template prefix `hosting.`. Store it in the hosting-service secret store. An empty key disables forwarding, including when the URL stays at the default.

Local email-service:

```bash
EMAIL_SERVICE_URL=http://localhost:8003
EMAIL_SERVICE_API_KEY=esk_your_service_key_here
```

Docker Compose passes the same variables through. The full list is in [Configuration](configuration.md).

## Request body

The forward runs after the database commit, on the same worker pool as webhook delivery. The API response does not wait for email-service.

`POST /api/v1/events` sends the hosting event data and one recipient hint. The hint is the acting user's email and user id, when the JWT included them. The body omits `language` so the company rule can choose `en` or `fr`.

The email copy drops sign-in links and tokens before it is stored. Dropped keys include `magic_link_url`, `token`, `raw_token`, and any `*_token` name. A value that is a sign-in URL is dropped too, including a `magic-link` path or a `token` query parameter. The webhook envelope still carries the original `data` object.

```json
{
  "service": "hosting",
  "event_type": "hosting.deployment.failed",
  "company_id": 42,
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "display_name": "My App",
    "app_version": "1.2.0",
    "error": "artifact_extract_failed"
  },
  "recipients": [
    {"email": "ada@acme.com", "user_id": 7}
  ]
}
```

`payload` is the webhook `data` object after that omission. hosting-service does not add `company_name`. email-service fills that variable from an earlier call for the company, or the template default applies. A failed deployment includes `error` (for example `artifact_extract_failed`).

When the JWT has no email, `recipients` is `[]`. email-service answers `202` with `skipped_reason: no_recipients`. hosting-service treats that response as delivered. `202` with `skipped_reason: no_rule` is delivered too.

Retries send this stored body again, including the same `idempotency_key`. The API key is not written into the outbox row or into logs.

The Shellui Actions deliveries API lists webhook rows only. Email rows stay on the outbox until `retry_webhooks` finishes them.

## Retries

`python manage.py retry_webhooks` retries email rows with webhook rows. The schedule is the one-minute cron in [Maintenance jobs](maintenance-jobs.md). Backoff is `30s * 2^(n-1)`, capped at 1 hour, for 8 attempts. HTTP timeout is `ACTIONS_WEBHOOK_TIMEOUT_SECONDS` (default 5s).

| Result | What hosting-service does |
| --- | --- |
| 2xx | Delivered. `skipped_reason` of `no_rule` or `no_recipients` is finished |
| 404, 408, 409, 425, 429, other 4xx not listed below, 5xx, timeouts, connection errors | Retry with the same body and `idempotency_key` |
| 429 or 503 with `Retry-After` | Retry. The wait is `Retry-After`, capped at 1 hour |
| 400, 401, 403, 405, 410, 413, 422 | Dead. That body is not sent again |

`404` retries, the same way a Shellui Actions webhook retries an inactive n8n workflow. See [n8n](n8n.md).

Finished rows are deleted with webhook deliveries after `EVENT_LOG_RETENTION_DAYS`.
