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

### Required runtime env (production)

| Variable | Notes |
|----------|--------|
| `SECRET_KEY` | Django sessions/CSRF |
| `IDENTITY_JWKS` or `IDENTITY_JWKS_URL` / `IDENTITY_JWKS_FILE` | JWT verification material |
| `HOSTING_APP_DOMAIN` | e.g. `shellui.app` (required when `DEBUG=false`) |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `HOSTING_BACKEND` | `filesystem` or S3 settings |

## Publish to Docker Hub

```bash
VERSION=0.1.0
IMAGE=shellui/hosting-service

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "${IMAGE}:${VERSION}" \
  -t "${IMAGE}:latest" \
  --push .
```

```bash
git tag -a "v${VERSION}" -m "Release ${VERSION}"
git push origin "v${VERSION}"
```

## Rollback

```bash
docker pull shellui/hosting-service:0.1.0
```
