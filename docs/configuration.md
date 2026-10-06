---
description: Environment variables for hosting-service, grouped by topic, with the defaults from settings and .env.example.
---

# Configuration

hosting-service reads configuration from environment variables. Copy [`.env.example`](../.env.example) to `.env` for local runs. Pass the same keys to Docker, Coolify, or your orchestrator in production.

An empty boolean uses the default. `1`, `true`, `yes`, and `on` are true. Any other value, including `false`, is false. Byte sizes accept a bare integer or a `K`, `M`, `G`, or `T` suffix. Each suffix is a multiple of 1024, so `100M` is 104857600 bytes.

## Required to start

`SECRET_KEY` is required in every mode. Django uses it to sign sessions and CSRF tokens. Generate one with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Required when DEBUG is false

The Docker image sets `DEBUG=false`. Startup fails until these are set:

| Variable | Purpose |
| --- | --- |
| `IDENTITY_ISSUER` | JWT `iss` must match this value |
| `IDENTITY_AUDIENCE` | JWT `aud` must match this value |
| `IDENTITY_JWKS_FILE` or `IDENTITY_JWKS` | Pinned JSON Web Key Set (JWKS). A URL fetch is refused |
| `HOSTING_APP_DOMAIN` | Domain used in API browse links, for example `shellui.app` |

`HOSTING_DEBUG_OPEN=true` is also refused while `DEBUG=false`. `JWT_HS256_FALLBACK_SECRET` is refused unless you also set `ALLOW_JWT_HS256_FALLBACK=true`.

## Runtime

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEBUG` | `false` | Local mode. The image sets `false`. Never enable it in production |
| `LOG_LEVEL` | `INFO`, or `DEBUG` when `DEBUG=true` | Python log level |
| `SETUP_TOKEN` | empty | One-time token for the web form that creates the first superuser when `DEBUG=false` |
| `HOSTING_SERVICE_PORT` | `8002` | Host port published by Docker Compose. Gunicorn inside the image listens on 8000 |
| `ALLOWED_HOSTS` | `localhost`, `127.0.0.1` | Comma-separated hostnames, no scheme |
| `CSRF_TRUSTED_ORIGINS` | local dev origins and `https://admin.shellui.com` | Full origins for Django admin form posts |
| `DJANGO_ADMIN_ENABLED` | `true` | `false` removes `/admin/` routes |

When `HOSTING_ALLOW_ANY_HOST` is on (the default while `DEBUG=true`), `ALLOWED_HOSTS` includes `*`. Otherwise the service adds `.{HOSTING_APP_DOMAIN}` so app subdomains are allowed.

## Identity and JWT

| Variable | Default | Purpose |
| --- | --- | --- |
| `IDENTITY_SERVICE_URL` | empty | identity-service base URL. Also the target for OAuth redirect sync |
| `IDENTITY_JWKS_URL` | `{IDENTITY_SERVICE_URL}/.well-known/jwks.json` | JWKS URL when no document is pinned. Local and dev only in production checks |
| `IDENTITY_JWKS_FILE` | empty | Path to a JWKS file. Relative paths are from the repository root |
| `IDENTITY_JWKS` | empty | JWKS JSON in the environment, used when no file is set |
| `IDENTITY_ISSUER` | empty | Expected `iss`. Required when `DEBUG=false` |
| `IDENTITY_AUDIENCE` | empty | Expected `aud`. Required when `DEBUG=false` |
| `JWKS_CACHE_TTL` | `900` | Seconds to cache a fetched JWKS document |
| `JWKS_TIMEOUT` | `15` | Seconds for one JWKS HTTP call |
| `JWKS_RETRIES` | `2` | Retries when fetching JWKS |
| `JWT_ALGORITHMS` | `RS256` | Comma-separated algorithms accepted for RS256 verification |
| `JWT_HS256_FALLBACK_SECRET` | empty | HS256 secret for local identity debug tokens. Set it to the identity `SECRET_KEY` |
| `ALLOW_JWT_HS256_FALLBACK` | `false` | Allow the HS256 secret when `DEBUG=false` |
| `IDENTITY_SYNC_TIMEOUT` | `10` | Seconds for the OAuth redirect sync call |

See [JWT and claim trust](claim-trust.md).

## Public URLs and serving

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOSTING_APP_DOMAIN` | `shellui.local` when `DEBUG=true`, else required | Domain written into API browse links |
| `HOSTING_APP_SCHEME` | `http` when `DEBUG=true`, else `https` | Scheme of those links |
| `HOSTING_ALLOW_ANY_HOST` | same as `DEBUG` | Accept any `Host` header. Leave this off in production |
| `HOSTING_PREVIEW_TTL_DAYS` | `7` | Days added to `expires_at` when a preview finalize succeeds |
| `HOSTING_SERVE_CACHE_TTL_SECONDS` | `45` | In-process cache of slug-to-app lookups. `0` disables it. Cleared on finalize and rollback |
| `HOSTING_DEBUG_OPEN` | `false` | Skip the company waitlist. Refused when `DEBUG=false`. [`.env.example`](../.env.example) sets `true` for local clones |

The public URL is `{scheme}://{slug}.{HOSTING_APP_DOMAIN}/`. Serving itself uses the first hostname label, not only this domain. See [Preview sites and public URLs](preview-and-serving.md).

## Quotas

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOSTING_MAX_APPS_PER_COMPANY` | `5` | App rows per company. Preview creates skip expired sites. `POST /hosting/v1/apps` counts every row |
| `HOSTING_MAX_DEPLOYMENTS_PER_APP` | `20` | Deployment rows kept per app, including superseded ones |
| `HOSTING_MAX_UPLOAD_BYTES` | `100M` | Maximum gzip archive size |
| `HOSTING_MAX_EXTRACT_FILES` | `5000` | Maximum regular files extracted from one archive |
| `HOSTING_MAX_EXTRACT_BYTES` | `500M` | Maximum total uncompressed size |
| `HOSTING_MAX_EXTRACT_FILE_BYTES` | same as the upload cap | Maximum size of one extracted file |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | `12M` | Django in-memory upload limit. The archive is still capped by `HOSTING_MAX_UPLOAD_BYTES` |

## Artifact storage

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOSTING_BACKEND` | `filesystem` | `filesystem` or `s3` |
| `MEDIA_ROOT` | `data/media`, `/app/data/media` in Docker | Filesystem root. Artifacts live in `artifacts/` under it |
| `HOSTING_KEY_PREFIX` | `hosting` | Key prefix in front of every artifact path |
| `AWS_STORAGE_BUCKET_NAME` | empty | Required when `HOSTING_BACKEND=s3` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | empty | S3 credentials |
| `AWS_S3_REGION_NAME` | `us-east-1` | Region. Inferred from the endpoint when possible |
| `AWS_S3_ENDPOINT_URL` | empty | Custom S3 endpoint. Leave empty for AWS |
| `AWS_S3_CUSTOM_DOMAIN` | empty | Public host for the bucket, if it differs from the endpoint |
| `AWS_S3_SIGNATURE_VERSION` | `s3v4` | Signature version |
| `AWS_S3_ADDRESSING_STYLE` | inferred | `path`, `virtual`, or `auto` |

Objects are stored at `{HOSTING_KEY_PREFIX}/{app_id}/deployments/{deployment_id}/artifact.tar.gz`. Extracted files sit under `extracted/` next to that archive. `app_id` is the app UUID, not the public slug.

## Database

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_DATABASE_URL` | empty | PostgreSQL DSN. Unset uses SQLite |
| `SQLITE_PATH` | `db.sqlite3`, `/app/data/db.sqlite3` in Docker | SQLite file |
| `POSTGRES_SSL_REQUIRE` | `true` when `DEBUG=false` | Require TLS to PostgreSQL. Set `false` for a private database without TLS |

## Cache and rate limits

`REDIS_URL` is optional. When it is set, Django uses Redis for the rate-limit cache. When it is unset, each process uses an in-memory cache. With `GUNICORN_WORKERS` greater than 1, set Redis so the counters are shared. `manage.py check --deploy` reports `authapi.W001` when production still uses the in-memory cache with multiple workers.

```bash
REDIS_URL=redis://redis:6379/0
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOSTING_RATE_LIMIT_ENABLED` | `true` | Turn the limits off. Leave them on in production |
| `HOSTING_RATE_LIMIT_DEPLOY` | `30` per 60s | Preview, create deployment, finalize, rollback |
| `HOSTING_RATE_LIMIT_UPLOAD` | `20` per 60s | Artifact upload |
| `HOSTING_RATE_LIMIT_DESTRUCTIVE` | `10` per 60s | App delete |
| `HOSTING_RATE_LIMIT_ACCESS_REQUEST` | `10` per 300s | Waitlist request |

Limits key on the authenticated user, then on the client IP. See [Security hardening](security-hardening.md) for `TRUSTED_PROXY_IPS`.

## CORS and HTTPS

| Variable | Default | Purpose |
| --- | --- | --- |
| `CORS_ALLOW_ALL_ORIGINS` | `true` | Allow browser calls from any origin |
| `CORS_ALLOW_CREDENTIALS` | `false` | Must stay `false` while all origins are allowed. That combination refuses to start |
| `CORS_ALLOWED_ORIGINS` | local dev origins, plus extras you append | Used when `CORS_ALLOW_ALL_ORIGINS=false` |
| `CORS_ALLOW_PRIVATE_NETWORK` | `true` | Private Network Access preflight header |
| `SECURE_SSL_REDIRECT` | on when `DEBUG=false` | Redirect HTTP to HTTPS |
| `SECURE_HSTS_SECONDS` | `31536000` when `DEBUG=false`, else `0` | HSTS max-age |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | on when `DEBUG=false` | Include subdomains in HSTS |
| `SECURE_HSTS_PRELOAD` | `false` | HSTS preload flag |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | on when `DEBUG=false` | Secure attribute on Django cookies |
| `TRUSTED_PROXY_IPS` | empty | Proxy IPs or CIDRs allowed to set `X-Forwarded-For` |

API auth is the Bearer JWT, not a cookie. Permissive CORS is the default for that reason. Token delivery after login is the identity OAuth redirect allowlist, not CORS.

## Gunicorn

The image entrypoint runs migrations, then Gunicorn. It does not start a worker process for cron. Schedule the commands in [Maintenance jobs](maintenance-jobs.md) yourself.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GUNICORN_WORKERS` | `2` | Worker processes |
| `GUNICORN_THREADS` | `2` | Threads per worker |
| `GUNICORN_TIMEOUT` | `120` | Seconds before Gunicorn kills a silent worker. Sized for large uploads |

## Shellui Actions

Webhooks do not need Redis. These variables tune delivery. The catalog and the admin API are in [Webhooks](actions.md).

| Variable | Default | Purpose |
| --- | --- | --- |
| `ACTIONS_OUTBOX_MAX_ATTEMPTS` | `8` | Attempts before a delivery is dead |
| `ACTIONS_WEBHOOK_TIMEOUT_SECONDS` | `5` | Timeout of one webhook POST |
| `ACTIONS_WEBHOOK_RETRY_LEASE_SECONDS` | `120` | How long one retry run holds a row |
| `ACTIONS_WEBHOOK_DISPATCH_WORKERS` | `4` | Threads used for post-commit delivery |
| `ACTIONS_WEBHOOK_SYNC_DELIVERY` | `false` | Deliver inside the request. Leave `false` outside tests |
| `ACTIONS_WEBHOOK_ALLOW_PRIVATE` | same as `DEBUG` | Allow webhook URLs that resolve to private or loopback addresses |

## Event log

| Variable | Default | Purpose |
| --- | --- | --- |
| `EVENT_LOG_RETENTION_DAYS` | `7` | Days to keep event-log rows and finished webhook deliveries |

`manage.py purge_expired_data` deletes older rows. Nothing in the container runs that command. See [Event log](event-log.md) and [Maintenance jobs](maintenance-jobs.md).

## Apex landing

| Variable | Default | Purpose |
| --- | --- | --- |
| `ROOT_REDIRECT_URL` | empty | Absolute URL. When set, apex `GET /` returns 301. App subdomains are unchanged |
| `SHELLUI_WEBSITE_URL` | `https://shellui.com` | Link on the landing page |
| `SHELLUI_DOCS_URL` | `https://docs.shellui.com` | Link on the landing page |
| `SHELLUI_PLAYGROUND_URL` | `https://playground.shellui.com` | Link on the landing page |
| `SHELLUI_GITHUB_URL` | `https://github.com/shellui` | Link on the landing page |
| `SHELLUI_AI_URL` | `https://shellui.ai` | Link on the landing page |

Leave `ROOT_REDIRECT_URL` empty when this process should show the hosting landing page. `GET /llms.txt` on the apex returns a short text description of the site.

## Error reporting

| Variable | Default | Purpose |
| --- | --- | --- |
| `SENTRY_DSN` | empty | Turns on Sentry. No personal data is attached |
| `SENTRY_ENVIRONMENT` | `development` or `production` from `DEBUG` | Sentry environment tag |
| `SENTRY_RELEASE` | the package version | Sentry release tag |
| `SENTRY_TRACES_SAMPLE_RATE` | `0` | Share of requests traced. `0` reports errors only |

## Related

- [Run hosting-service](getting-started.md)
- [Security hardening](security-hardening.md)
- [PUBLISH.md](../PUBLISH.md)
