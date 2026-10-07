---
description: The EventLog table for every hosting event, how long rows are kept, and the admin API that lists them.
---

# Event log

hosting-service records every [catalog event](actions.md#event-catalog) in one table, `EventLog`, whether or not a webhook rule exists for it. Django admin shows the rows under **Hosting > Log events**.

The same events can also be delivered as [webhooks](actions.md). Retention for both is the hourly purge in [Scheduled jobs](maintenance-jobs.md).

## Row format

| Column | Content |
| --- | --- |
| `id` | Sequential id |
| `company_id` | Identity company id the event belongs to |
| `user_id` | Identity user id who created the app, deployed, or deleted the app |
| `event_type` | Catalog event type |
| `data` | Event payload, compacted as described below |
| `created_at` | When the event happened |

`data` is the webhook payload with empty values removed (`null`, empty strings, empty lists, and `false`). `company_id` and `user_id` are removed from `data` because they are columns. `actor_email` is added when the request token carried an email.

hosting-service has no user or company tables. Ids and emails come from the identity-service JWT. Deployment `succeeded` and `failed` events name the caller who finalized the deployment.

Two indexes serve listing, the retention check, and the purge: `(company_id, created_at)` and `(company_id, user_id, created_at)`.

## Retention

Retention is one setting for the whole service: `EVENT_LOG_RETENTION_DAYS` (default 7).

Schedule `purge_expired_data` every hour. It deletes events older than the retention, together with delivered and dead webhook deliveries, in short batches:

```bash
python manage.py purge_expired_data
python manage.py purge_expired_data --dry-run
python manage.py purge_expired_data --max-seconds 300
```

`--dry-run` counts rows and deletes nothing. `--max-seconds 300` stops after 300s. The next run continues. The container runs this every hour at minute 17. If events older than the retention plus one day are still stored, the job is not running. The admin dashboard and **Hosting > Log events** then show an error that asks you to check it. See [Scheduled jobs](maintenance-jobs.md).

## Admin API

Callers must be Django staff or a company owner, with a Bearer JWT from identity-service. Staff may pass any `company_id` query parameter. Company owners are limited to the JWT `company_id`. The same value is accepted. Another company returns 403.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/actions/event-log` | Newest first, paginated |
| `GET` | `/api/v1/actions/event-log/{id}` | One event |
| `GET` | `/api/v1/actions/event-log/types` | Event types with `label` and `description` |
| `GET` | `/api/v1/actions/event-log/retention` | `data_retention_days`, `oldest_event_at`, `stale_events` |

Filters on `GET /api/v1/actions/event-log`:

| Parameter | Meaning |
| --- | --- |
| `event_type` | One type, or several separated by commas |
| `user_id` | Identity user id |
| `user` | Case-insensitive part of the actor email |
| `created_after` | ISO 8601 datetime, inclusive |
| `created_before` | ISO 8601 datetime, exclusive |
| `page`, `page_size` | Pagination. `page_size` up to 100, default 20 |

Rows have the same shape as identity-service `GET /api/v1/events`:

```json
{
  "id": 87,
  "company_id": 1,
  "created_at": "2026-10-02T09:14:03.120Z",
  "event_type": "hosting.deployment.failed",
  "label": "Deployment failed",
  "user_id": 42,
  "user_email": "ada@example.com",
  "data": {
    "app_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "docs",
    "slug": "vpzzsxvzsmp7",
    "display_name": "Docs",
    "deployment_id": "660e8400-e29b-41d4-a716-446655440001",
    "app_version": "1.4.0",
    "shellui_version": "0.5.0",
    "status": "failed",
    "error": "artifact_extract_failed",
    "actor_email": "ada@example.com"
  }
}
```

`shellui_version` in that sample is the version string stored on the deployment. It is not the hosting-service release.

## Related

- [Webhooks](actions.md)
- [Scheduled jobs](maintenance-jobs.md)
