---
description: How hosting-service runs webhook retries and data retention inside the container, and how to watch those jobs.
---

# Scheduled jobs

hosting-service runs two maintenance jobs on a schedule. The Docker image runs them for you. With `REDIS_URL` set (required when `DEBUG=false`), there is nothing else to install.

| Job | Schedule | What happens if it never runs |
| --- | --- | --- |
| `purge_expired_data` | Every hour, at minute 17, for at most 5 minutes | The event log and finished webhook and email deliveries grow without a limit. The admin panel reports `stale_events` once events are more than one day past retention |
| `retry_webhooks` | Every minute | Failed [webhook](actions.md) deliveries and [email-service](email.md) posts are never retried. The first attempt still goes out right after each event |

Both jobs finish after one or two indexed queries when there is nothing to do.

## How it works

The container starts two processes:

- **Gunicorn**, the web app
- a **Celery worker with an embedded beat** (`celery -A config worker --beat`). Beat sends each job on time. The worker runs it. One process with a pool of 2 threads means an hourly purge does not delay webhook retries.

Redis is the message broker. The jobs are the same code as the `purge_expired_data` and `retry_webhooks` management commands.

The entrypoint watches both processes. A `SIGTERM` (for example `docker stop` or a redeploy) is passed to both, so in-flight work finishes. If either process exits, the entrypoint stops the other and the container exits, so Docker or Coolify restarts it.

| Variable | Default | Purpose |
| --- | --- | --- |
| `REDIS_URL` | unset | Redis for the shared cache and the job broker. **Required when `DEBUG=false`.** Without it the container logs `REDIS_URL is required when DEBUG is false` and exits with status 1. That includes `SCHEDULER_ENABLED=false`. With `DEBUG=true` the jobs do not run, the container logs a warning, and the web app still starts |
| `CELERY_BROKER_URL` | `REDIS_URL` | Use a different Redis for the jobs. It does not replace `REDIS_URL`, which the cache needs |
| `SCHEDULER_ENABLED` | `true` | `false` keeps the worker out of this container. Use it with a dedicated worker container, or run the commands yourself. `REDIS_URL` is still required in production |
| `CELERY_WORKER_CONCURRENCY` | `2` | Threads in the worker. 2 lets a purge and a retry run at the same time |

The worker uses the same settings as the web app: `LOG_LEVEL`, stdout logging, Sentry when `SENTRY_DSN` is set, and the Postgres timeouts.

Each run logs one summary line, for example:

```text
INFO [apps.actions.tasks] retry_webhooks: processed=0 delivered=0 retried=0 dead=0 run_id=1234
```

### Several containers

Every job takes a Redis lock before it starts (`SET NX` with an expiry: 2 minutes for `retry_webhooks`, 15 minutes for `purge_expired_data`). When another container already runs the same job, the run is skipped and logs `skipped, another run is in progress`. Several replicas can each run beat, and a job never runs twice at the same time. The lock expires on its own if a container dies mid-run.

Jobs use their own queue (`hosting-service`) and lock keys, so one Redis can serve hosting-service and other Shellui services.

### Run the worker in its own container

The image takes a mode as its command:

| Command | Starts |
| --- | --- |
| `web` (default) | migrations, `check --deploy`, then Gunicorn and the worker (unless `SCHEDULER_ENABLED=false`) |
| `worker` | only the worker with beat. No migrations, no web server. Needs `REDIS_URL` (`CELERY_BROKER_URL` alone is enough only with `DEBUG=true`) |
| anything else | runs that command as `appuser`, for example `python manage.py createsuperuser` |

```yaml
services:
  hosting-service:
    image: shellui/hosting-service:latest
    env_file: .env
    environment:
      SCHEDULER_ENABLED: "false"
  hosting-worker:
    image: shellui/hosting-service:latest
    command: worker
    env_file: .env
    restart: unless-stopped
```

The web container runs migrations. The worker needs the same database. With SQLite, both containers must mount the same `/app/data` volume. Prefer Postgres for this setup.

### Turn the in-container scheduler off

Set `SCHEDULER_ENABLED=false` and run the management commands from your own scheduler, with the same image, environment variables, and database as the web service.

- `retry_webhooks` every minute
- `purge_expired_data --max-seconds 300` every hour, at minute 17

```bash
python manage.py retry_webhooks
python manage.py purge_expired_data --max-seconds 300
```

## `purge_expired_data`

Deletes rows older than `EVENT_LOG_RETENTION_DAYS` (default **7 days**):

- [event log](event-log.md) rows, including staff-only scheduled job events (`company_id` null, same retention)
- finished webhook deliveries (`delivered` or `dead`) and their attempts. `pending` and `failed` rows stay so retries continue
- finished email-service outbox rows, on the same rule
- [scheduled job runs](#monitoring) older than 7 days

```bash
python manage.py purge_expired_data
python manage.py purge_expired_data --dry-run
python manage.py purge_expired_data --max-seconds 300
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--batch-size` | `2000` | Rows deleted per statement |
| `--max-seconds` | `0` (no limit) | Stop early. Output says `complete=false` and the next run continues |
| `--dry-run` | off | Count expired rows without deleting. A dry run is not recorded |

Output example:

```text
purge_expired_data: deleted events=1840 webhook_deliveries=12 email_events=3 scheduled_job_runs=168 complete=true run_id=1235
```

The hourly minute is 17 so the job does not start at the same time as other hourly work. A missed run is caught by the next one. `stale_events` appears only after a full day without a successful purge.

## `retry_webhooks`

Retries webhook deliveries whose first attempt failed, and email-service posts in the same pass. Backoff is in [Webhooks](actions.md) and [Email notifications](email.md).

```bash
python manage.py retry_webhooks
python manage.py retry_webhooks --batch-size 50 --max-seconds 50 --concurrency 4
```

Keep `--max-seconds` (default 50) under 60 so a run finishes before the next one is due. Overlapping runs are still safe: rows are claimed with a lease (`ACTIONS_WEBHOOK_RETRY_LEASE_SECONDS`, default 120 seconds).

## Monitoring

Every run of both jobs is recorded, whether the in-container beat or your own scheduler started it. Django staff can read this. Company owners cannot.

### What each run records

The management command records its own run. Each run writes one `ScheduledJobRun` row:

| Field | Content |
| --- | --- |
| `job` | `retry_webhooks` or `purge_expired_data` |
| `trigger` | `celery` (in-container beat) or `command` (your scheduler, or a manual run) |
| `status` | `running`, `succeeded`, or `failed` |
| `started_at`, `finished_at`, `duration_ms` | Timing |
| `counts` | Items processed. See below |
| `error_key`, `error_class`, `error_message` | On failure: a stable key (`database_error`, `redis_error`, `timeout`, `network_error`, `interrupted`, `unexpected_error`), the exception class, and a short message without URL query strings, credentials, or tokens |
| `host` | Host name and process id |
| `event_log_id` | The platform event written for this run |

`counts` for `retry_webhooks`: `webhook_deliveries_attempted`, `webhook_deliveries_succeeded`, `webhook_deliveries_failed` (will be retried), `webhook_deliveries_given_up` (now `dead`), and the same four with the `email_events_` prefix.

`counts` for `purge_expired_data`: rows deleted (`events`, `webhook_deliveries`, `email_events`, `scheduled_job_runs`) and `complete` (false when `--max-seconds` ran out).

Some runs are not stored:

- **Skipped runs.** When another container holds the lock, the run increments the `skipped_locked` counter and does not insert a row.
- **Dry runs.** `--dry-run` changes nothing, so it is not recorded.

Runs are kept 7 days. `purge_expired_data` deletes older ones. The latest timestamps (`ScheduledJobState`) and the metric counters (`ScheduledJobCounter`) are never purged. A `running` row older than the job's lock expiry (2 minutes for `retry_webhooks`, 15 minutes for `purge_expired_data`) is marked `failed` with `error_key=interrupted` by the next run.

### Health

A job is overdue when its last successful run is older than 3 times its interval:

| Job | Interval | Overdue after |
| --- | --- | --- |
| `retry_webhooks` | 1 minute | 3 minutes |
| `purge_expired_data` | 1 hour | 2 hours 15 minutes |

Before the first successful run, the clock starts when the monitoring tables were created (the migration). Each job has one `health` value:

- `disabled`: `SCHEDULER_ENABLED=false` and no run was ever recorded
- `failing`: the last finished run failed
- `overdue`: no successful run within the limit above
- `healthy`: none of the above

Runs you start yourself are monitored the same way, so `SCHEDULER_ENABLED=false` with a working scheduler reports `healthy`.

Two more signals cover the scheduler itself:

- `redis_reachable`: a `PING` on the broker (`null` when no broker is configured)
- beat heartbeat: each time beat publishes a job it stores the time in Redis (`hosting-service:scheduler:beat:heartbeat`). `beat_stale` is true when the scheduler is enabled and beat published nothing for 3 minutes

### Staff API

The endpoints use the same Bearer JWT as the other admin endpoints. They need Django `is_staff`. Company owners get `403`. Calls without a token get `401`. No `company_id` is required.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/scheduled-jobs` | `scheduler_enabled`, `redis_reachable`, `beat_last_seen_at`, `beat_stale`, and one entry per job |
| `GET` | `/api/v1/scheduled-jobs/{job}/runs?limit=20&status=failed` | Recent runs, newest first. `limit` is 1 to 100 |
| `GET` | `/api/v1/scheduled-jobs/runs/{id}` | One run, the webhook attempts it made, and the email-service rows it retried |

Each job entry includes `health`, `overdue`, `interval_seconds`, `overdue_after_seconds`, `last_run`, `last_success_at`, `last_failure_at`, `last_skipped_at`, `last_duration_ms`, `last_counts`, `next_expected_at`, `last_24h` (`succeeded`, `failed`), and `skipped_locked_total`.

A finished run also writes a staff-only platform event, `hosting.scheduled_job.succeeded` or `hosting.scheduled_job.failed`. Those events have `company_id` null. They are not Shellui Actions webhook rules, they are not forwarded to email-service, and they do not appear on a company's event log.

### From a run to its webhooks and emails

Every delivery attempt stores `trigger`:

- `dispatch`: the first try, right after the event
- `automatic_retry`: a `retry_webhooks` run, with `scheduled_job_run_id`

While a job runs, hosting-service sends `X-Request-ID: sjr-{run_id}` on webhook POSTs and on email-service `POST /api/v1/events`. Log lines for that run use the same request id.

Staff can open `GET /api/v1/scheduled-jobs/runs/{id}` for the attempts (every company) and the email rows. `GET /api/v1/actions/deliveries?scheduled_job_run_id={id}` lists webhook deliveries of the token company that this run touched. Each attempt on `GET /api/v1/actions/deliveries/{id}` includes `scheduled_job_run_id` for staff.

Company owners see `trigger` on their own attempts. They do not see `scheduled_job_run_id`. Filtering deliveries by `scheduled_job_run_id` as an owner returns `403`.

### Failed runs

A failed run is stored with `status=failed`, logged at ERROR with a sanitized message, reported to Sentry when `SENTRY_DSN` is set (tags `scheduled_job`, `scheduled_job_trigger`, `scheduled_job_run_id`), and the management command exits with status 1. If Redis is down when a Celery run tries to take its lock, the run is recorded as `failed` with `error_key=redis_error`.

### Prometheus

`GET /hosting/v1/metrics/all` includes the scheduled job metrics. It needs Django staff or a personal access token with `access_global_metrics`. `GET /hosting/v1/metrics` is one company and never includes these series, or another company's series. Values come from the database, so they match whichever Gunicorn worker answers.

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `shellui_hosting_scheduled_job_runs_total` | counter | `job`, `status` | Finished runs: `succeeded`, `failed`, `skipped_locked` |
| `shellui_hosting_scheduled_job_items_total` | counter | `job`, `kind` | Items processed. `kind` is a `counts` name |
| `shellui_hosting_scheduled_job_last_success_timestamp_seconds` | gauge | `job` | Unix time of the last successful run (0 before the first one) |
| `shellui_hosting_scheduled_job_last_run_timestamp_seconds` | gauge | `job` | Unix time the last run started |
| `shellui_hosting_scheduled_job_last_run_duration_seconds` | gauge | `job` | Duration of the last finished run |
| `shellui_hosting_scheduled_job_overdue` | gauge | `job` | 1 when overdue |
| `shellui_hosting_scheduler_enabled` | gauge | none | 1 when `SCHEDULER_ENABLED` is true |
| `shellui_hosting_scheduler_redis_up` | gauge | none | 1 when the broker answers `PING`. Absent when no broker is configured |
| `shellui_hosting_scheduler_beat_last_seen_timestamp_seconds` | gauge | none | Unix time beat last published a job. Absent before the first one |

## Related

- [Event log](event-log.md)
- [Webhooks](actions.md)
- [Email notifications](email.md)
- [Configuration](configuration.md#scheduled-jobs)
