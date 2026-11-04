---
description: Run hosting-service in the Shellui local dev stack (shellui/shellui dev/docker-compose.yml) with env-driven settings.
---

# Local dev stack

The shared compose file lives in [shellui/shellui](https://github.com/shellui/shellui) at `dev/docker-compose.yml`. Clone this repository next to the other Shellui repos, then start the stack from `shellui/dev`:

```bash
cd shellui/shellui/dev
cp .env.local.example .env.local
docker compose --env-file .env.local up
```

hosting-service is built with `target: dev` from this repository's [Dockerfile](../Dockerfile). Python dependencies live in `/opt/venv` inside the image; your checkout is bind-mounted at `/app`. The container runs migrations, then `python manage.py runserver 0.0.0.0:8000` with autoreload.

## Ports and URLs

| Role | Value |
| --- | --- |
| Browser / public API | [http://localhost:8003](http://localhost:8003) |
| Compose service name (internal DNS) | `hosting` |
| Container listen port | `8000` |

Hosted app previews use `HOSTING_APP_DOMAIN=shellui.local` and `HOSTING_APP_SCHEME=http`. Add preview slugs to `/etc/hosts` as described in [Run hosting-service](getting-started.md).

## Environment variables

In `dev/.env.local`, variables that could clash across services are prefixed with `HOSTING_`. Compose maps them to the names hosting-service reads at runtime. The table lists the **container** names (what [Configuration](configuration.md) documents).

### Required for the stack

| Container variable | Example (local stack) | Notes |
| --- | --- | --- |
| `SECRET_KEY` | `HOSTING_SECRET_KEY` in `.env.local` | Any non-empty value while `DEBUG=true`. Use a generated string, not a production secret |
| `DEBUG` | `true` | Enables runserver, local SQLite/Postgres defaults, and optional Redis |
| `POSTGRES_DATABASE_URL` | `postgres://hosting:hosting@postgres:5432/hosting` | One database per service on the shared Postgres instance |
| `REDIS_URL` | `redis://redis:6379/2` | Shared Redis; use a dedicated DB index for hosting (compose sets the index) |
| `HOSTING_APP_DOMAIN` | `shellui.local` | Preview subdomain base |
| `HOSTING_APP_SCHEME` | `http` | Preview links and OAuth redirect origins |
| `HOSTING_DEBUG_OPEN` | `true` | Skips the company waitlist gate locally |
| `IDENTITY_ISSUER` | `http://localhost:8001` | Public issuer URL (JWT `iss`). Must match tokens from identity-service |
| `IDENTITY_AUDIENCE` | Same as identity-service `JWT_AUDIENCE` | JWT `aud` |
| `IDENTITY_SERVICE_URL` | `http://identity:8000` | Server-to-server calls (OAuth redirect sync). Internal DNS, not `localhost` |
| `IDENTITY_JWKS_URL` | `http://identity:8000/.well-known/jwks.json` | JWKS fetch from inside the compose network |

Keep **issuer and browser URLs** on `http://localhost:<host port>`. Use **`http://<service>:8000`** for JWKS, identity API calls, and other container-to-container traffic.

Optional while `DEBUG=true`: `IDENTITY_ISSUER` and `IDENTITY_AUDIENCE` are not enforced at startup, but JWT verification fails if they do not match the tokens identity-service issues. Set them to the same values identity uses locally.

### Recommended for the stack

| Container variable | Example | Notes |
| --- | --- | --- |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,hosting,.shellui.local` | `DEBUG=true` also enables `HOSTING_ALLOW_ANY_HOST` by default |
| `CSRF_TRUSTED_ORIGINS` | `http://localhost:8003,http://127.0.0.1:8003,http://localhost:5173,http://localhost:5174` | Django admin and cross-origin form posts from Admin and Dashboard |
| `EMAIL_SERVICE_URL` | `http://email:8000` | Forward notification events to email-service |
| `EMAIL_SERVICE_ALLOW_PRIVATE` | `true` | Required for internal `http://email:8000` URLs |
| `SCHEDULER_ENABLED` | `true` | Webhook retries and purge jobs when `REDIS_URL` is set |
| `SECURE_SSL_REDIRECT` | `false` | Plain HTTP locally |
| `SESSION_COOKIE_SECURE` | `false` | Django admin over HTTP |
| `CSRF_COOKIE_SECURE` | `false` | Django admin over HTTP |

### Optional

| Container variable | Default in stack | Notes |
| --- | --- | --- |
| `HOSTING_BACKEND` | `filesystem` | Artifact storage under `/app/data/media` |
| `SQLITE_PATH` | `/app/data/db.sqlite3` | Used only when `POSTGRES_DATABASE_URL` is empty |
| `MEDIA_ROOT` | `/app/data/media` | Bind mount or named volume for artifacts |
| `CORS_ALLOWED_ORIGINS` | (empty) | `CORS_ALLOW_ALL_ORIGINS=true` is the default for API Bearer auth |
| `JWT_HS256_FALLBACK_SECRET` | (empty) | Match identity `SECRET_KEY` only if you use HS256 debug tokens |
| `EMAIL_SERVICE_API_KEY` | (empty) | Leave empty to disable email forwarding |

Full defaults and production rules are in [Configuration](configuration.md).

## Run this repo alone (without the full stack)

Use the repository [docker-compose.yml](../docker-compose.yml) or [Run hosting-service](getting-started.md) with [`.env.example`](../.env.example). That path defaults to port **8003** on the host (`HOSTING_SERVICE_PORT`) and `IDENTITY_SERVICE_URL=http://localhost:8001` when identity runs on the standard dev-stack identity port.

## CSS and static files

The dev image does not run Tailwind. `static/css/site.css` is committed for the apex landing. After you change `assets/css/` or templates, run on the host:

```bash
npm ci && npm run build:css
```

With `DEBUG=true`, WhiteNoise serves updated CSS from `static/` without collectstatic.

## Production image unchanged

`docker build` with no `--target` still builds the final production stage (Gunicorn, collectstatic, health check). The publish workflow is unchanged.
