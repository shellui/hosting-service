# Email notifications

hosting-service forwards every hosting event to [email-service](https://github.com/shellui/email-service) when `EMAIL_SERVICE_API_KEY` is set, so a company email rule can send mail. `hosting.deployment.failed` is on by default there. With the key unset, hosting-service does not call email-service.

Webhook [Shellui Actions](actions.md) are a separate path. A webhook rule does not send mail, and mail does not require a webhook rule.

## Events that are forwarded

hosting-service posts each catalog event it already emits. email-service decides whether to send.

| Event type | Suggested mail |
| ---------- | -------------- |
| `hosting.deployment.failed` | On, until the company turns the rule off |
| `hosting.app.created` | Off, until the company turns the rule on |
| `hosting.app.deleted` | Off, until the company turns the rule on |
| `hosting.deployment.created` | Off, until the company turns the rule on |
| `hosting.deployment.succeeded` | Off, until the company turns the rule on |

Company owners change those rules in email-service. hosting-service does not store them.

## Configuration

Set both variables on the hosting-service process. Names match the [email-service integration contract](https://github.com/shellui/email-service/blob/main/docs/integration.md).

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `EMAIL_SERVICE_URL` | `https://email.shellui.com` | Origin only. hosting-service appends `/api/v1/events`. |
| `EMAIL_SERVICE_API_KEY` | unset | Service key with prefix `esk_`. Sent as `Authorization: Bearer`. |

Issue the key in email-service for service `hosting`, lane `transactional`, and template prefix `hosting.`. Store it in the hosting-service secret store. An empty key disables forwarding, including when the URL is left at the default.

Local email-service example:

```bash
EMAIL_SERVICE_URL=http://localhost:8003
EMAIL_SERVICE_API_KEY=esk_your_service_key_here
```

Docker Compose passes the same variables through. See [configuration.md](configuration.md).

## Request body

The forward runs after the database commit, on the same worker pool as webhook delivery. The request thread does not wait on email-service.

`POST /api/v1/events` sends the hosting event payload and one recipient hint. The hint is the acting user's email and user id, when the token included them. `language` is omitted so the company rule can choose `en` or `fr`.

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

`payload` is the same object stored on the webhook envelope under `data`. hosting-service does not store a company name, so `company_name` is absent and the suggested template uses its fallback. A failed deployment includes `error` (for example `artifact_extract_failed`).

Retries send this stored body again, including the same `idempotency_key`. The API key is not written into the outbox row or into logs.

The Shellui Actions deliveries API lists webhook rows only. Email rows stay on the outbox until `retry_webhooks` finishes them.

## Retries

`python manage.py retry_webhooks` (the one-minute cron in [actions.md](actions.md)) retries email rows with webhook rows. Backoff is `30s * 2^(n-1)`, capped at 1 hour, for 8 attempts. HTTP timeout is `ACTIONS_WEBHOOK_TIMEOUT_SECONDS` (default 5s).

| Result | What hosting-service does |
| ------ | ------------------------- |
| 2xx | Delivered. A disabled rule is still 202, with no message. |
| 409, 429 | Retry. 429 and 503 honor `Retry-After`, capped at 1 hour. |
| 5xx, timeouts, connection errors | Retry |
| 400, 401, 403, 404, 422 | Dead. The body is not sent again. |

Finished rows are deleted with webhook deliveries after `EVENT_LOG_RETENTION_DAYS`.

A 404 from email-service is dead. That differs from n8n, where 404 means the workflow is inactive and stays retryable. See [n8n.md](n8n.md) for webhook rules.
