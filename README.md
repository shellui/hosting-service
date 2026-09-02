# hosting-service

`hosting-service` is a Django backend that hosts Shellui microfrontend apps: deployment API under `/hosting/v1/*` and **public static serving** at `{slug}.{HOSTING_APP_DOMAIN}`.

It authenticates with JWTs issued by [identity-service](https://github.com/shellui/identity-service), stores deployment tarballs in **S3** (or local filesystem), extracts them for browsing, and manages company access waitlists, app slugs, and deployments.

## Features

- REST API under `/hosting/v1/*` for access, apps, deployments, and stats
- **Browsable hosted apps** on any domain — slug is the first subdomain label (e.g. `https://{slug}.shellui.app/` or `http://{slug}.shellui.local:8002/`)
- Company hosting access waitlist (`CompanyHostingAccess`)
- Globally unique auto-generated site slugs for public URLs; company-scoped app names for API/CLI
- JWT verification via identity-service JWKS (local document or `IDENTITY_JWKS_URL`)
- Pluggable artifact backend: **S3** or **filesystem**
- OpenAPI docs (Swagger + ReDoc)

## Project structure

- `config/` — Django settings and URL routing
- `apps/authapi/` — JWKS JWT authentication
- `apps/hosting/` — apps, deployments, access, static serving

## Main endpoints

| Area | Path |
|------|------|
| Health | `GET /hosting/v1/health` |
| Access | `GET/POST /hosting/v1/access`, `POST /hosting/v1/access/request` |
| Apps | `GET/POST /hosting/v1/apps`, `GET /hosting/v1/apps/{name\|uuid}` |
| Deployments | `GET/POST /hosting/v1/apps/{app}/deployments` |
| Upload | `PUT /hosting/v1/apps/{app}/deployments/{id}/upload` |
| Finalize / rollback | `POST .../finalize`, `POST .../rollback` |
| Stats | `GET /hosting/v1/stats` |
| Django admin | `/admin/` |
| **Browse** | `GET https://{site_slug}.{HOSTING_APP_DOMAIN}/` |
| OpenAPI | `/api/docs/`, `/api/docs/redoc/` |

Auth header: `Authorization: Bearer <access_token>` from identity-service.

## Quick start (local)

### 1. Start identity-service

Hosting validates JWTs from identity. Run identity on port **8000** (see `identity-service/README.md`).

### 2. Start hosting-service

```bash
cd hosting-service
uv sync
cp .env.example .env   # SECRET_KEY and JWKS are pre-filled for local dev
uv run python manage.py migrate
uv run python manage.py runserver 8002
```

Open `http://localhost:8002/` for Swagger / ReDoc.

With `DEBUG=true`, `HOSTING_DEBUG_OPEN` defaults to **on** — any logged-in company can deploy without waitlist approval.

To require approval in dev, set `HOSTING_DEBUG_OPEN=false` and approve a company:

```bash
uv run python manage.py approve_hosting_access 1
```

### 3. Fake app domains locally

Hosted apps are served on subdomains, not path prefixes. Add entries to `/etc/hosts` after deploying:

```
127.0.0.1  vpzzsxvzsmp7.shellui.local
127.0.0.1  hosting.shellui.local
```

Use `HOSTING_APP_DOMAIN=shellui.local` and `HOSTING_APP_SCHEME=http` in `.env` (defaults in `.env.example`). This domain is used for **API browse links** only — the server accepts app requests on **any** hostname whose first label is the site slug.

In `DEBUG`, `HOSTING_ALLOW_ANY_HOST` defaults to **on** (`ALLOWED_HOSTS` includes `*`), so you only need `/etc/hosts` entries — no per-domain Django config.

The deployment API stays at `http://localhost:8002/hosting/v1/`. Browsable apps are at `http://{site_slug}.shellui.local:8002/` (or any domain you point at the server).

### 4. Deploy from a shellui project

In your shellui repo (with `hosting.url` in config):

```bash
shellui login
shellui deploy --build
```

Each deploy creates a **new preview site** (new slug) unless you set `hosting.slug` in config to redeploy an existing one you own. Preview sites expire after **7 days**; redeploying to the same slug resets the timer.

The CLI prints the browsable URL, slug, and expiry, e.g.:

```
Browse:       http://vpzzsxvzsmp7.shellui.local/
Slug:          vpzzsxvzsmp7
Expires:      2026-09-09T...
```

Add the slug to `/etc/hosts` pointing at `127.0.0.1`, then open it on port **8002**.

To redeploy later, add the slug to config:

```json
"hosting": {
  "url": "http://localhost:8002",
  "slug": "vpzzsxvzsmp7"
}
```

## Public URL configuration

| Variable | Purpose |
|----------|---------|
| `HOSTING_APP_DOMAIN` | Canonical domain for API browse links (default `shellui.local` when `DEBUG=true`, e.g. `shellui.app` in production) |
| `HOSTING_APP_SCHEME` | `http` (local) or `https` (production). Defaults to `http` when `DEBUG=true`, else `https` |
| `HOSTING_ALLOW_ANY_HOST` | When `true` (default in `DEBUG`), accept any `Host` header — useful with `/etc/hosts` |
| `HOSTING_PREVIEW_TTL_DAYS` | Preview site lifetime in days (default `7`) |
| `HOSTING_DEBUG_OPEN` | Skip company waitlist (auto-on when `DEBUG=true`) |

**Local:**

```
http://{site_slug}.shellui.local:8002/
```

**Production:**

```
https://{site_slug}.shellui.app/
```

Run the deployment API on a separate host (e.g. `hosting.shellui.app`). App subdomains are served by the same process via a catch-all route that excludes `/hosting/`, `/api/`, and `/admin/`.

## Environment

See `.env.example` for all settings. Key quotas:

- `HOSTING_MAX_APPS_PER_COMPANY` (default `5`)
- `HOSTING_MAX_DEPLOYMENTS_PER_APP` (default `20`)
- `HOSTING_MAX_UPLOAD_BYTES` (default `100M`)

Deployment artifacts are stored at `{slug}/deployments/{id}/artifact.tar.gz` and extracted to `{prefix}extracted/` for static serving.

## Docker

```bash
docker build -t hosting-service .
docker run --rm -p 8002:8000 -v hosting-service-data:/app/data --env-file .env hosting-service
```

## License

See [LICENSE](LICENSE).
