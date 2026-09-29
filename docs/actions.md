# Shellui Actions (hosting webhooks)

Company owners (and staff) can react when hosting events happen using **webhook Shellui Action rules** in the **Shellui admin API**. Each rule maps a **catalog event type** (for example `hosting.deployment.succeeded`) to an HTTPS **webhook** endpoint.

Hosting-service delivers webhooks directly on its domain events. There is no central actions service and no message bus.

---

## How it works

```text
Domain code calls emit_event(type, company_id, payload)
        │
        ▼
Match enabled webhook ActionRule rows for that company + event type
        │
        ▼
Insert ActionOutbox row(s) in the same DB transaction
        │
        ▼
transaction.on_commit → best-effort delivery (timeout-bounded HTTP, off the request thread)
        │
        ▼
DeliveryAttempt audit log; retries via manage.py retry_webhooks
```

- **No Celery / Redis required** for Shellui Actions.
- API paths do not block on slow external HTTP: delivery runs only after commit (default 5s timeout).
- Delivery is **at-least-once**; dedupe on the envelope `id` (same value as the `webhook-id` header).

---

## Event catalog (`hosting.*`)

| Event type | When it fires |
| ---------- | ------------- |
| `hosting.app.created` | A hosted app record is created |
| `hosting.app.deleted` | A hosted app and its deployments are removed |
| `hosting.deployment.created` | A deployment row is created (draft, ready for upload) |
| `hosting.deployment.succeeded` | Finalize completed; deployment is active |
| `hosting.deployment.failed` | Artifact extract failed during finalize |

### Envelope shape

CloudEvents-inspired JSON (same headers and signing as identity-service Shellui Actions):

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

---

## Admin REST API

Same paths as identity-service (Bearer JWT from identity-service):

- `GET /api/v1/actions/events` — catalog with `sample_envelope`
- `GET/POST /api/v1/actions/rules` — list/create webhook rules
- `GET/PATCH/DELETE /api/v1/actions/rules/<id>`
- `POST /api/v1/actions/rules/<id>/send-test`
- `GET /api/v1/actions/deliveries` — paginated delivery log
- `GET /api/v1/actions/deliveries/<uuid>` — detail with attempts
- `POST /api/v1/actions/deliveries/<uuid>/requeue`

Staff may pass `?company_id=` on these routes. Company owners use the `company_id` claim in the JWT only.

---

## Retries (cron)

Backoff: `30s * 2^(n-1)` capped at 1 hour, max 8 attempts. Permanent HTTP 4xx (except 408 and 429) marks a delivery dead.

```bash
python manage.py retry_webhooks --batch-size 50 --max-seconds 50 --concurrency 4
```

Example cron (every minute):

```cron
* * * * * cd /app && python manage.py retry_webhooks >> /var/log/retry_webhooks.log 2>&1
```

Run the same command in Docker sidecars or platform schedulers that can exec into the hosting-service container.
