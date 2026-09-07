# Publish and deploy

How to build, publish, and run the `shellui/hosting-service` Docker image on [Docker Hub](https://hub.docker.com/r/shellui/hosting-service).

Publishing is **manual** — there is no CI workflow for Docker Hub yet.

## Image overview

| Item        | Value                                                               |
| ----------- | ------------------------------------------------------------------- |
| Registry    | Docker Hub                                                          |
| Repository  | `shellui/hosting-service`                                           |
| Listen port | `8000`                                                              |
| Data volume | `/app/data` (SQLite `db.sqlite3` + filesystem artifacts under `media/`) |

The image contains application code and collected static files. Secrets and runtime configuration are supplied via environment variables at container start (see `.env.example`).

## Pre-release checklist

Complete these steps **before** building and pushing a release tag. Prefer the automated script (same checks run on PRs to `main`):

```bash
./tools/pre-release-check.sh
```

| Step | What it verifies |
|------|------------------|
| Version alignment | `pyproject.toml` version matches a dated `CHANGELOG.md` entry (`## [x.y.z] - YYYY-MM-DD`) and `uv.lock` |
| Build secrets | `.env` / `*.sqlite3` not tracked; `.gitignore` / `.dockerignore` exclude `.env`; built image has no `/app/.env` |
| Image smoke test | Container serves `/hosting/v1/health` with `status=ok` (static `IDENTITY_JWKS` + `HOSTING_APP_DOMAIN`) |

Options: `--skip-docker`, `--image TAG`, `--port PORT`.

GitHub Actions: [`.github/workflows/pre-release.yml`](.github/workflows/pre-release.yml) on PRs to `main` and **workflow_dispatch**.

Manual equivalents (if you are not using the script):

### 1. Version alignment

Ensure these match the release version (e.g. `0.2.1`):

- `version` in `pyproject.toml` (OpenAPI / API metadata via `config.settings.VERSION`)
- `CHANGELOG.md` entry with date
- Git tag `v0.2.1` (optional but recommended; not enforced by the script)
- CI green on the release commit (`.github/workflows/ci.yml` + pre-release workflow)

### 2. No secrets in the build context

```bash
# .env must not be tracked or copied into the image
test ! -f .env || grep -qE '^\.env$' .gitignore

docker build -t shellui/hosting-service:release-check .
docker run --rm --entrypoint sh shellui/hosting-service:release-check \
  -c 'test ! -f /app/.env && echo "OK: .env not in image"'
```

`.dockerignore` excludes `.env`, `*.sqlite3`, `.git`, and local tooling artifacts. Only `.env.example` is included (placeholders only).

### 3. Smoke test the image

Covered by `./tools/pre-release-check.sh`.

## Publish to Docker Hub

### Prerequisites

1. Docker Hub account with push access to the `shellui` organization (or your namespace).
2. Docker CLI logged in:

```bash
docker login
```

3. Clean git tree at the commit you intend to release.

### Tagging

For semver release `0.2.1`, typical Docker Hub tags:

| Tag      | Purpose                                  |
| -------- | ---------------------------------------- |
| `0.2.1`  | Exact release (pin in production)        |
| `0.2`    | Latest patch in the 0.2 line             |
| `latest` | Newest published release (use with care) |

### Option A — single platform (fastest, not recommended, see option B)

From the repository root:

```bash
VERSION=0.2.1
IMAGE=shellui/hosting-service

docker build -t "${IMAGE}:${VERSION}" .
docker push "${IMAGE}:${VERSION}"

# Optional extra tags
docker tag "${IMAGE}:${VERSION}" "${IMAGE}:0.2"
docker tag "${IMAGE}:${VERSION}" "${IMAGE}:latest"
docker push "${IMAGE}:0.2"
docker push "${IMAGE}:latest"
```

### Option B — multi-arch (recommended for production)

If you build on Apple Silicon, a plain `docker build` may produce `linux/arm64` only. Most cloud VMs expect `linux/amd64`. Publish both with buildx:

```bash
VERSION=0.2.1
IMAGE=shellui/hosting-service

docker buildx create --use --name multi 2>/dev/null || docker buildx use multi

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "${IMAGE}:${VERSION}" \
  -t "${IMAGE}:latest" \
  --push .
```

### Git tag (recommended)

```bash
VERSION=0.2.1
git tag -a "v${VERSION}" -m "Release ${VERSION}"
git push origin "v${VERSION}"
```

## Deploy

Pull and run the published image:

```bash
docker volume create hosting-service-data

docker run -d \
  --name hosting-service \
  -p 8002:8000 \
  -v hosting-service-data:/app/data \
  -e SECRET_KEY='replace-with-generated-key' \
  -e ALLOWED_HOSTS='hosting.example.com,*.shellui.app' \
  -e CSRF_TRUSTED_ORIGINS='https://hosting.example.com' \
  -e HOSTING_APP_DOMAIN='shellui.app' \
  -e IDENTITY_JWKS='{"keys":[...]}' \
  shellui/hosting-service:0.2.1
```

The entrypoint runs migrations on start, then starts Gunicorn on port 8000.

### Required runtime env vars (production)

| Variable | Notes |
|----------|--------|
| `SECRET_KEY` | Django sessions/CSRF |
| `IDENTITY_JWKS` or `IDENTITY_JWKS_URL` / `IDENTITY_JWKS_FILE` | JWT verification material |
| `HOSTING_APP_DOMAIN` | e.g. `shellui.app` (required when `DEBUG=false`) |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `HOSTING_BACKEND` | `filesystem` or S3 settings |

### Optional runtime env vars

| Variable | Notes |
|----------|--------|
| `CORS_ALLOW_ALL_ORIGINS` | Default `true` (Bearer JWT is the API auth boundary). Set `false` + `CORS_ALLOWED_ORIGINS` for lock-down. |
| `IDENTITY_SERVICE_URL` | Enables OAuth redirect sync for preview origins on identity-service |
| `ROOT_REDIRECT_URL` | Optional 301 for apex `/` |
| `POSTGRES_DATABASE_URL` | Use Postgres instead of SQLite |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` | Error reporting |
| `AWS_*` | django-storages when `HOSTING_BACKEND=s3` |

Do not list every preview slug in CORS env — OAuth redirect sync on identity handles login bounce origins.

## Security notes

| Topic | Status |
|-------|--------|
| `.env` in image | Excluded via `.dockerignore` |
| Runtime `SECRET_KEY` / JWKS | Must be provided; never baked into the image |
| `DEBUG` | Defaults to `false` in Dockerfile |
| SQLite / artifact files | Excluded from image; use volume or S3 + Postgres |

Do not commit `.env` or real AWS keys to git. Do not pass secrets as Docker build args unless you accept they may appear in image history.

## Rollback

Pull and run a previous tag or digest:

```bash
docker pull shellui/hosting-service:0.2.0
```

Data in `hosting-service-data` (or Postgres / S3) is independent of the image tag; test migrations when downgrading.
