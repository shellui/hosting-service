---
description: Run hosting-service locally with Docker Compose or uv, approve a company, and deploy a Shellui app.
---

# Run hosting-service

This page takes you from a clone to a browsable preview. You start hosting-service, point it at identity-service, approve your company, then run `shellui deploy`.

Run identity-service first, on port 8000. hosting-service checks the JWTs identity-service issues. Start with the [identity-service docs](https://docs.shellui.com/identity/).

## Start with Docker Compose

Docker Compose builds the image, maps port 8002 to Gunicorn on port 8000, and stores SQLite plus artifacts in the `hosting-service-data` volume. You need Docker and Git:

```bash
git clone https://github.com/shellui/hosting-service.git
cd hosting-service
cp .env.example .env
docker compose up --build
```

`.env.example` already sets `SECRET_KEY`, `IDENTITY_SERVICE_URL=http://localhost:8000`, and `HOSTING_DEBUG_OPEN=true` for local runs. Change `SECRET_KEY` before any shared environment.

The API is at [http://localhost:8002/hosting/v1/health](http://localhost:8002/hosting/v1/health). Stop the stack with `docker compose down`. The named volume keeps the database and uploaded files.

## Start from a checkout

Use this path when you are changing the Python code. You need [uv](https://docs.astral.sh/uv/) and Node.js 22:

```bash
uv sync
cp .env.example .env
npm ci
npm run build:css
uv run python manage.py migrate
uv run python manage.py runserver 8002
```

`npm run build:css` writes the apex landing stylesheet. When you edit `templates/` or `assets/css/`, run `npm run watch:css` in a second terminal. Django reloads templates while `DEBUG=true`. New Tailwind class names appear after that CSS rebuild.

## Create the first admin user

With `DEBUG=true` and an empty user table, [http://localhost:8002/](http://localhost:8002/) shows a one-time form for the first Django superuser. After that, the same URL is the apex landing page, with links to Swagger, ReDoc, and Django admin.

In production (`DEBUG=false`), create the superuser from the shell:

```bash
uv run python manage.py createsuperuser
```

Or set `SETUP_TOKEN` and open `/?setup_token=your_setup_token_here` once. The form is refused when the token does not match.

## Skip or pass the waitlist

Creating an app requires an approved company. `.env.example` sets `HOSTING_DEBUG_OPEN=true`, which skips that check. The code default is off, and `DEBUG=true` does not turn it on by itself. The process refuses to start if `HOSTING_DEBUG_OPEN=true` while `DEBUG=false`.

To enforce the waitlist locally, set `HOSTING_DEBUG_OPEN=false`, request access from the API, then approve the company:

```bash
uv run python manage.py approve_hosting_access 1
```

`1` is the identity-service company id. Staff can also `POST /hosting/v1/access` with `status` set to `approved`. Details are in [Company access](company-access.md).

## Point a hostname at a preview

Hosted apps are served on a subdomain, not under a path prefix. For local links, keep `HOSTING_APP_DOMAIN=shellui.local` and `HOSTING_APP_SCHEME=http`. After the first deploy, add the printed slug to `/etc/hosts`:

```text
127.0.0.1  vpzzsxvzsmp7.shellui.local
```

Open `http://vpzzsxvzsmp7.shellui.local:8002/`. With `DEBUG=true`, `HOSTING_ALLOW_ANY_HOST` defaults to on, so Django accepts that `Host` header. [Preview sites and public URLs](preview-and-serving.md) explains which hostnames map to a slug.

## Deploy from a Shellui project

In the app repository, set `hosting.url` in `shellui.config.json`, sign in, and deploy:

```bash
shellui login
shellui deploy --build
```

`shellui login` stores an identity-service access token. `shellui deploy` sends `POST /hosting/v1/preview`, uploads `dist/web/` as `artifact.tar.gz`, then finalizes. `--build` runs `shellui build` first. If `dist/web/` is missing, the CLI builds even without `--build`.

Omit `hosting.slug` to create a new preview. To publish again to the same site, add the slug the CLI printed:

```json
{
  "hosting": {
    "url": "http://localhost:8002",
    "slug": "vpzzsxvzsmp7"
  }
}
```

`hosting.app` is ignored for preview deploys. Use `hosting.slug`, or pass `--slug`. Other commands: `shellui deploy history`, and `shellui deploy rollback --to 1.2.3` or `--deployment` with the deployment UUID.

## Run it in production

The image defaults to `DEBUG=false`. It will not start until `IDENTITY_ISSUER`, `IDENTITY_AUDIENCE`, a pinned JWKS document, and `HOSTING_APP_DOMAIN` are set. Use a pinned tag of `shellui/hosting-service`.

Before the first request, finish these steps:

1. Set `POSTGRES_DATABASE_URL` if you do not want SQLite on the `/app/data` volume.
2. Set `REDIS_URL` when `GUNICORN_WORKERS` is greater than 1, so rate limits are shared.
3. Schedule `retry_webhooks` and `purge_expired_data`. The container does not run them. See [Maintenance jobs](maintenance-jobs.md).
4. Put each preview origin on the identity OAuth redirect allowlist, or set `IDENTITY_SERVICE_URL` so hosting-service registers it during deploy.
5. Run [tools/prod-config-check.sh](../tools/prod-config-check.sh) against the platform URL, for example `https://shellui.app`, not against a customer slug.

Every variable is in [Configuration](configuration.md). Production defaults for HTTPS, CORS, and proxies are in [Security hardening](security-hardening.md). Image tags and the Coolify notes are in [PUBLISH.md](../PUBLISH.md).
