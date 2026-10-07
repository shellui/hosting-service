# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

<!---
## [Unreleased] - yyyy-mm-dd

### ✨ Feature - for new features
### 🛠 Improvements - for general improvements
### 🚨 Changed - for changes in existing functionality
### ⚠️ Deprecated - for soon-to-be removed features
### 📚 Documentation - for documentation update
### 🗑 Removed - for removed features
### 🐛 Bug Fixes - for any bug fixes
### 🔒 Security - in case of vulnerabilities
### 🏗 Chore - for tidying code

See for sample https://raw.githubusercontent.com/favoloso/conventional-changelog-emoji/master/CHANGELOG.md
-->

## [0.6.0] - 2026-10-07

### ✨ Feature

- The image runs `retry_webhooks` every minute and `purge_expired_data` hourly at minute 17, with a Redis lock so one run proceeds across replicas.
- Staff read job health at `GET /api/v1/scheduled-jobs`. Scheduler series stay on `GET /hosting/v1/metrics/all`.
- With `EMAIL_SERVICE_API_KEY` set, hosting events are posted to email-service, and every event is stored for `GET /api/v1/actions/event-log`.

### 🚨 Changed

- Production (`DEBUG` false) requires `REDIS_URL`. The container exits if it is missing.

### 📚 Documentation

- The handbook covers setup, apps, preview URLs, company access, scheduled jobs, email, and the API.

### 🐛 Bug Fixes

- A `company_id` query that matches the token is accepted on Shellui Actions admin routes. Django admin deletes remove stored artifacts, and a failed extract stays `failed`.

### 🔒 Security

- Private email-service URLs need `EMAIL_SERVICE_ALLOW_PRIVATE`. Webhook and email bodies omit tokens, sign-in links, and secret-shaped fields.
- Access logs omit query strings and Referer. Sentry drops those, authorization headers, and stack locals.

### ⬆️ Upgrade notes

- Apply migrations through `0004_scheduled_job_runs`, set `REDIS_URL`, and drop any external cron for these two jobs (or set `SCHEDULER_ENABLED=false`).

## [0.5.0] - 2026-09-29

### ✨ Feature

- **Shellui Actions webhooks:** Deliver `hosting.*` events through a DB-backed outbox with signed envelopes and SSRF-safe HTTP. Manage rules via the company admin API at `/api/v1/actions/*` (aligned with identity-service). Failed deliveries retry with backoff via `python manage.py retry_webhooks`.
- **n8n integration:** `whsec_` signing secrets, UTF-8 JSON bodies, `X-Shellui-Event` and `X-Shellui-Delivery-Attempt` headers, `Retry-After` on 429/503, and retryable 404s. Rotate with `POST …/rotate-secret`; the secret is only returned on create and rotate (`has_secret` and `secret_hint` otherwise).
- **Redis cache:** Optional `REDIS_URL` shares rate-limit counters across workers (LocMem stays the default). Deploy check `authapi.W001` warns when production runs LocMem with `GUNICORN_WORKERS` > 1.

### 📚 Documentation

- **Shellui Actions:** [docs/actions.md](docs/actions.md) covers webhook rules, the event catalog, and the retry cron.
- **n8n:** [docs/n8n.md](docs/n8n.md) and a [signature verification example](docs/examples/verify-shellui-webhook.mjs).
- **Redis:** `REDIS_URL` documented in `.env.example`, [README.md](README.md), [PUBLISH.md](PUBLISH.md), [docker-compose.yml](docker-compose.yml), and [docs/security-hardening.md](docs/security-hardening.md).
- **Agent notes:** Root `AGENTS.md` with Shellui writing and design guidelines for coding agents.

### 🐛 Bug Fixes

- **Pre-release smoke test:** Supplies `IDENTITY_ISSUER` / `IDENTITY_AUDIENCE`, disables the SSL redirect for local curls, and dumps container logs if health never goes ready.
- **HTTPS webhooks on Python 3.14:** `webhook_transport.py` uses identity-service pinned TLS connect (`PinnedHTTPSConnection`, IPv6 Host/SNI parsing).
- **Admin send-test:** Sends fresh UUID and timestamp sample values; the events catalog preview stays static.

### 🔒 Security

- **Webhook SSRF (matches identity v0.6.0):** Rejects non-global resolved addresses, including CGNAT `100.64.0.0/10`, plus NAT64, 6to4, and IPv4-compatible IPv6 literals. Changing a webhook URL clears `allow_private_urls` until a superuser re-enables it.
- **Client IP behind proxies:** With `TRUSTED_PROXY_IPS` set, rate limits key on the rightmost untrusted `X-Forwarded-For` hop, not the client-controlled leftmost one. Hops are normalized, IPv4-mapped proxies match CIDRs, and IPv6 buckets by /64.

### ⬆️ Upgrade notes

- **Migrations:** Run them after upgrading (`apps.actions` adds the webhook outbox tables).
- **Webhook retries:** Schedule `python manage.py retry_webhooks` every minute (`* * * * *`).
- **Multiple workers:** Set `REDIS_URL` (e.g. `redis://redis:6379/0`) when `GUNICORN_WORKERS` > 1.
- **Reverse proxy:** Set `TRUSTED_PROXY_IPS` to your proxy CIDRs so rate limits see the real client IP ([docs/security-hardening.md](docs/security-hardening.md)).

## [0.4.1] - 2026-09-22

### 🛠 Improvements

- **Homepage:** Overall refresh of branding, layout, and styling.

## [0.4.0] - 2026-09-18

### 📚 Documentation

- **Prod config check:** `./tools/prod-config-check.sh` runs post-deploy HTTPS smoke tests (mirrors identity-service); documented in README and PUBLISH.md.
- **Security guides:** [docs/security-hardening.md](docs/security-hardening.md) (CORS, rate limits, transport, admin isolation, Postgres SSL) and [docs/claim-trust.md](docs/claim-trust.md) (JWT privileged claims, JWKS pinning).
- **Access approval:** README, `.env.example`, and PUBLISH.md cover staff-only approval and the explicit `HOSTING_DEBUG_OPEN` opt-in.

### 🐛 Bug Fixes

- **Pre-release smoke test:** Supplies `IDENTITY_ISSUER` / `IDENTITY_AUDIENCE`, disables the SSL redirect for local curls, and dumps container logs if health never goes ready.

### 🔒 Security

- **First-run bootstrap:** With an empty user table and `DEBUG=false`, the `/` superuser form is hidden and POST returns 403 without a valid `SETUP_TOKEN` (query param, hidden field, or `X-Setup-Token` header). Prefer `python manage.py createsuperuser` in production.
- **Staff-only access approval (H-11):** Only staff can move `POST /hosting/v1/access` requests to `approved` or `denied`; company owners can no longer self-approve.
- **Fail-closed debug bypass (M-28):** Only an explicit truthy `HOSTING_DEBUG_OPEN` skips the waitlist; `DEBUG=true` no longer enables it.
- **Production hardening (M-01, M-07, M-23, H-12, #12):**
  - CORS allow-all requires `CORS_ALLOW_CREDENTIALS=false` (startup fails otherwise).
  - HSTS and secure cookies when `DEBUG=false`.
  - Postgres `ssl_require` by default (`POSTGRES_SSL_REQUIRE=false` to opt out).
  - `IDENTITY_ISSUER`, `IDENTITY_AUDIENCE`, and pinned JWKS required in production.
  - Optional `DJANGO_ADMIN_ENABLED=false`.
- **Rate limits (M-02, #12):** Cache-backed limits on preview/deploy, upload, finalize, rollback, delete, and access requests.
- **Tar extraction (M-25, M-26, M-27):** Caps on file count, total uncompressed size, and per-file size, with atomic rollback. Member paths are normalized and `..` components rejected; static serving rejects literal and URL-encoded path traversal.

## [0.3.0] - 2026-09-12

### ✨ Feature

- **Apex landing page:** `shellui.app` gets a shellui.ai-style page with a light/dark toggle and links to the website, docs, playground, GitHub, and shellui.ai. Leave `ROOT_REDIRECT_URL` empty to show it.

### 🛠 Improvements

- **Faster app serving (#4):** One storage round-trip per file, no `index.html` checks for static assets, a short slug-to-app cache (`HOSTING_SERVE_CACHE_TTL_SECONDS`, default 45s, cleared on deploy), and `immutable` Cache-Control for content-hashed assets.
- **Landing copy:** Shellui wordmark, deploy-ready copy with a `shellui login` / `shellui deploy` example, and a `/llms.txt` overview for agents.

### 📚 Documentation

- **Root redirect:** `ROOT_REDIRECT_URL` is optional; unset it on the hosting apex to show the landing page.

## [0.2.1] - 2026-09-07

### ✨ Feature

- **Prometheus metrics:** `GET /hosting/v1/metrics` and `/hosting/v1/metrics/all` for apps, deployments, artifacts, and access. Requires a staff or company-owner JWT or PAT (same model as storage-service and identity-service).

### 🛠 Improvements

- **Swagger from Admin:** Swagger UI auto-applies the Shellui session token when opened from Admin (same preauthorize flow as identity-service and storage-service).

### 📚 Documentation

- **README and PUBLISH.md:** Refreshed for metrics, Swagger preauthorize, and Docker Hub publish/deploy examples.

## [0.2.0] - 2026-09-04

### ✨ Feature

- **Custom 404:** Friendly HTML page for missing, expired, or unpublished app subdomains.
- **OAuth redirect sync:** Create, redeploy, and delete forward the caller's JWT to identity-service (`IDENTITY_SERVICE_URL`) to add or remove the site origin on the OAuth redirect allowlist. Hosted shells log in without manual allowlist edits.

### 🚨 Changed

- **Permissive API CORS:** Defaults to `CORS_ALLOW_ALL_ORIGINS=true` with `CORS_ALLOW_CREDENTIALS=false` (Bearer JWT auth). Preview origins no longer need per-slug `CORS_ALLOWED_ORIGINS` entries.

### 🐛 Bug Fixes

- **App subdomains serve every path:** `{slug}.shellui.app` serves the hosted site for all paths, including `/admin`. Admin, API, and docs stay on the apex, so React Router refreshes no longer land on Django admin.

### 🔒 Security

- **Dependency bumps:** Clear `pip-audit` findings with Django `6.0.8`, cryptography `50.0.0`, djangorestframework `3.17.2`, requests `2.33.0`, and PyJWT `2.13.0`.

### 🏗 Chore

- **CI:** GitHub Actions runs Django tests, `uv lock --check`, `pip-audit`, gitleaks, lychee link checks, and a Docker build on PRs and `main`/`develop`.
- **Pre-release checks:** `./tools/pre-release-check.sh` and `.github/workflows/pre-release.yml` run on PRs to `main`.

## [0.1.0] - 2026-09-03

### ✨ Feature

- **Initial service:** Django project with JWT auth, company access waitlist, app and deployment management, and stats API under `/hosting/v1/*`, bootstrapped from storage-service patterns.
- **Preview deploys:** `POST /hosting/v1/preview` creates a new slug per deploy, with optional slug redeploy and a 7-day TTL.
- **Subdomain serving:** Public static sites at `https://{site_slug}.shellui.app/` (local dev: `/etc/hosts` + `HOSTING_APP_DOMAIN=shellui.local`).
- **Finalize and browse:** Deployment finalize extracts `artifact.tar.gz`; API responses include `urls.url`.
- **App deletion:** `DELETE /hosting/v1/apps/{ref}` removes the app, its deployments, and stored artifacts.
- **Apex redirect:** Optional `ROOT_REDIRECT_URL` for a 301 from apex `/` (e.g. to https://shellui.com). Unset keeps the landing page; app subdomains are unaffected.
- **Waitlist bypass:** `approve_hosting_access` management command for local and production.

### 🗑 Removed

- **Compatibility ranges:** Dropped app compatibility ranges and `GET /hosting/v1/apps/{app}/resolve`; preview hosting always serves the current deployment.
