# hosting-service

hosting-service deploys and serves Shellui apps, one subdomain per site. Shellui is free, open-source, and MIT-licensed: a microfrontend shell with shared navigation, authentication, storage, and administration.

## What the image contains

The production image on Docker Hub is:

- **Base**: `python:3.15-slim`
- **Port**: 8000
- **Entrypoint**: `/app/tools/docker-entrypoint.sh`
- **App user**: `appuser` (non-root)

After preparing `/app/data` as root, the entrypoint runs migrations, Gunicorn, and a Celery worker as `appuser`.

## Run the image

Point `REDIS_URL` at Redis, and mount `/app/data` for SQLite and uploaded files. Replace `your_secret_key_here` with at least 50 random characters before you start the container.

The command below publishes port 8000. Redis must be running at the host named in `REDIS_URL`. An empty `POSTGRES_DATABASE_URL` selects SQLite.

```bash
docker volume create hosting-service-data
docker run -d \
  --name hosting-service \
  -p 8000:8000 \
  -v hosting-service-data:/app/data \
  -e SECRET_KEY=your_secret_key_here \
  -e DEBUG=false \
  -e ALLOWED_HOSTS=hosting.example.com \
  -e CSRF_TRUSTED_ORIGINS=https://hosting.example.com \
  -e HOSTING_APP_DOMAIN=apps.example.com \
  -e IDENTITY_SERVICE_URL=https://identity.example.com \
  -e IDENTITY_ISSUER=https://identity.example.com \
  -e IDENTITY_AUDIENCE=your_jwt_audience_here \
  -e REDIS_URL=redis://your_redis_host_here:6379/0 \
  -e POSTGRES_DATABASE_URL="" \
  shellui/hosting-service:latest
```

The Compose file below starts Redis on the same network. `REDIS_URL` uses the service name `redis`.

```yaml
services:
  redis:
    image: redis:8-alpine
  hosting-service:
    image: shellui/hosting-service:latest
    ports:
      - "8000:8000"
    environment:
      SECRET_KEY: your_secret_key_here
      DEBUG: "false"
      ALLOWED_HOSTS: hosting.example.com
      CSRF_TRUSTED_ORIGINS: https://hosting.example.com
      HOSTING_APP_DOMAIN: apps.example.com
      IDENTITY_SERVICE_URL: https://identity.example.com
      IDENTITY_ISSUER: https://identity.example.com
      IDENTITY_AUDIENCE: your_jwt_audience_here
      REDIS_URL: redis://redis:6379/0
      POSTGRES_DATABASE_URL: ""
    volumes:
      - hosting-service-data:/app/data
    depends_on:
      - redis
volumes:
  hosting-service-data:
```

## Required environment variables

`config/env_registry.py` lists these variables as required. The image sets `DEBUG=false`. An empty `POSTGRES_DATABASE_URL` selects SQLite at `/app/data/db.sqlite3`.

From a checkout, `python manage.py generate_env --host hosting.example.com` prints a fresh `SECRET_KEY`.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Signs sessions and cross-site request forgery (CSRF) tokens and must be at least 50 characters. |
| `DEBUG` | Production mode. The image sets `false`. |
| `ALLOWED_HOSTS` | Public host names, comma-separated, no scheme |
| `CSRF_TRUSTED_ORIGINS` | Full HTTPS origin of this service |
| `HOSTING_APP_DOMAIN` | Domain for hosted apps, for example `shellui.app` |
| `IDENTITY_SERVICE_URL` | identity-service origin for OAuth redirect sync and JSON Web Key Set (JWKS) fetch |
| `IDENTITY_ISSUER` | JSON Web Token (JWT) `iss` claim, the identity-service URL |
| `IDENTITY_AUDIENCE` | JWT `aud` claim |
| `REDIS_URL` | Shared cache and job broker |
| `POSTGRES_DATABASE_URL` | PostgreSQL connection string. Leave empty to use SQLite. |

The [hosting-service configuration](https://docs.shellui.com/hosting/configuration/) lists every other variable and its default.

## Release tags

The publish workflow builds `linux/amd64` and `linux/arm64`, then tags `shellui/hosting-service` from the Git tag. A release named `v0.11.0` pushes the tags below. Later versions follow the same rules.

| Tag | When it is pushed |
| --- | --- |
| `0.11.0` | Full version of `v0.11.0`, with the leading `v` removed |
| `0.11` | Major and minor of that release |
| `latest` | A stable release, and a manual run of the publish workflow |

On a GitHub prerelease, `latest` stays on the previous stable image.

## OpenTelemetry

Telemetry stays off until `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Pass these when you export to a collector. The protocol is HTTP protobuf. Do not start the container under `opentelemetry-instrument`.

| Variable | Purpose |
| --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector base URL. Empty keeps telemetry off |
| `OTEL_EXPORTER_OTLP_HEADERS` | Exporter headers, including collector auth |
| `OTEL_SERVICE_NAME` | Overrides the default `hosting-service` |
| `OTEL_RESOURCE_ATTRIBUTES` | Resource tags, for example `deployment.environment=production,cloud.region=eu` |

## Health check

The image health check calls `GET /health/live` on `http://127.0.0.1:8000`. HTTP 200 means the web process is up. Postgres and Redis are outside this probe.

The first 60s are a start period, so a first-boot migration can finish before a failure counts.

For status details, call `GET /hosting/v1/health`. That route is public.

## Where to read more

Source, docs, changelog, license, and the Shellui site:

- [hosting-service repository](https://github.com/shellui/hosting-service)
- [hosting-service docs](https://docs.shellui.com/hosting/)
- [Changelog](https://github.com/shellui/hosting-service/blob/develop/CHANGELOG.md)
- [MIT license](https://github.com/shellui/hosting-service/blob/develop/LICENSE)
- [Shellui](https://shellui.com)
