---
description: Shellui Actions webhook rules for hosting events, the admin API, signing, and retries.
---

# Hosting webhooks

Company owners and staff can POST a signed JSON body to an HTTPS endpoint when a hosting event happens. Each Shellui Actions rule maps one catalog event, such as `hosting.deployment.succeeded`, to one webhook URL.

hosting-service delivers those webhooks itself. There is no central actions service and no message bus.

## How a delivery runs

Domain code calls `emit_event` inside the database transaction that changed the app or deployment:

1. The event is written to the [event log](event-log.md), whether or not a rule matches.
2. Each enabled webhook rule for that company and event type gets an outbox row in the same transaction.
3. After commit, a background thread POSTs the envelope. The API response does not wait for your server.
4. Each try is stored as a delivery attempt. Further tries come from `manage.py retry_webhooks`.

Delivery does not need Celery or Redis. The default HTTP timeout is 5s (`ACTIONS_WEBHOOK_TIMEOUT_SECONDS`). Delivery is at-least-once. Retries reuse the envelope `id`, which is also the `webhook-id` header. Dedupe on that value.

The n8n setup, including a signature check, is in [n8n](n8n.md). Scheduling the retry command is in [Maintenance jobs](maintenance-jobs.md).

## Event catalog

| Event type | When it fires |
| --- | --- |
| `hosting.app.created` | A hosted app row is created |
| `hosting.app.deleted` | A hosted app and its deployments are removed |
| `hosting.deployment.created` | A deployment row is created and waiting for an upload |
| `hosting.deployment.succeeded` | Finalize finished and the deployment is active |
| `hosting.deployment.failed` | Extract failed during finalize |

The body is UTF-8 JSON with non-ASCII characters left as characters (`ensure_ascii=false`). Verify the signature over the raw body bytes, not over a re-serialized object.

Extra headers: `X-Shellui-Event`, `X-Shellui-Delivery-Attempt`. Signing secrets are plain text or Standard Webhooks `whsec_` plus base64. Shellui decodes the `whsec_` suffix and uses those bytes as the HMAC key.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "hosting.deployment.succeeded",
  "time": "2026-09-24T13:30:00+00:00",
  "company": { "id": 1 },
  "data": {
    "app_id": "550e8400-e29b-41d4-a716-446655440000",
    "deployment_id": "660e8400-e29b-41d4-a716-446655440001",
    "status": "active"
  }
}
```

The `id` values above are samples. A real delivery uses a new id, and the same id again on every retry of that delivery.

## Admin API

Paths match identity-service. Authorize with a Bearer JWT. Staff may pass any `company_id` query parameter. Company owners are limited to the `company_id` claim. They may omit the parameter or repeat their own id. Another company returns 403.

- `GET /api/v1/actions/events`: catalog, including a `sample_envelope` for each type
- `GET` and `POST /api/v1/actions/rules`: list or create webhook rules. Create returns `secret` once when one was generated
- `GET`, `PATCH`, and `DELETE /api/v1/actions/rules/{id}`
- `POST /api/v1/actions/rules/{id}/rotate-secret`: new signing secret, returned once
- `POST /api/v1/actions/rules/{id}/send-test`
- `GET /api/v1/actions/deliveries`: paginated delivery log
- `GET /api/v1/actions/deliveries/{uuid}`: one delivery and its attempts
- `POST /api/v1/actions/deliveries/{uuid}/requeue`

Later reads of a rule expose `has_secret` and `secret_hint` (the last four characters), not the secret.

## Retries

Backoff is `30s * 2^(n-1)`, capped at 1 hour, with at most 8 attempts (`ACTIONS_OUTBOX_MAX_ATTEMPTS`).

| Result | Retry? |
| --- | --- |
| 2xx | No. The delivery is delivered |
| 404, 408, 409, 425, 429 | Yes. 404 covers an inactive n8n workflow |
| 400, 401, 403, 405, 410, 413, 422 | No. The delivery is dead |
| Other 4xx | Yes |
| 5xx, timeouts, connection errors | Yes |
| 429 or 503 with `Retry-After` | Yes. The delay is the larger of the backoff and `Retry-After`, still capped at 1 hour |

```bash
python manage.py retry_webhooks --batch-size 50 --max-seconds 50 --concurrency 4
```

Example cron, every minute:

```cron
* * * * * cd /app && python manage.py retry_webhooks >> /var/log/retry_webhooks.log 2>&1
```

Run that command from cron, a sidecar, or your platform scheduler. The hosting-service container does not run it for you. Delivered and dead deliveries are deleted after `EVENT_LOG_RETENTION_DAYS` by `purge_expired_data`. See [Maintenance jobs](maintenance-jobs.md).

Webhook URLs that resolve to a private or loopback address are blocked unless the rule has **allow private URLs** (staff) or `ACTIONS_WEBHOOK_ALLOW_PRIVATE` is true. When that variable is unset, it follows `DEBUG`.
