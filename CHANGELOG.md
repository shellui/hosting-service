# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-09-12

### 🛠 Improvements

- Faster hosted-app serving (#4): one storage round-trip per file (no exists-before-open), skip `index.html` existence checks for static assets, short in-process slug→App cache (`HOSTING_SERVE_CACHE_TTL_SECONDS`, default 45, auto-cleared on deploy), and long-lived `immutable` Cache-Control for content-hashed assets (Vite-style `name-hash.ext`).
- Apex marketing landing: Shellui wordmark (shellui.ai-style), deploy-ready copy with `shellui login` / `shellui deploy` example, and `/llms.txt` overview for agents.

### ✨ Feature

- Apex landing page for `shellui.app` (shellui.ai-style UI, light/dark toggle, links to website / docs / playground / GitHub / shellui.ai). Leave `ROOT_REDIRECT_URL` empty to use it instead of redirecting to shellui.com.

### 📚 Documentation

- Clarify that `ROOT_REDIRECT_URL` is optional; unset it on the public hosting apex to show the new landing.

## [0.2.1] - 2026-09-07

### ✨ Feature

- Added Prometheus metrics (`GET /hosting/v1/metrics`, `GET /hosting/v1/metrics/all`) for apps, deployments, artifacts, and access — staff or company-owner JWT / PAT (same auth model as storage-service and identity-service).

### 🛠 Improvements

- Swagger UI now auto-applies the Shellui session access token when docs are opened from Admin (same `swagger_ui.js` preauthorize flow as identity-service / storage-service).

### 📚 Documentation

- Refresh [README](README.md) and [PUBLISH.md](PUBLISH.md) for `0.2.1` (metrics, Swagger Admin preauthorize, Docker Hub publish/deploy examples).

## [0.2.0] - 2026-09-04

### 🚨 Changed

- **Permissive API CORS:** default `CORS_ALLOW_ALL_ORIGINS=true` with `CORS_ALLOW_CREDENTIALS=false` (Bearer JWT auth). Hosted preview origins no longer need per-slug `CORS_ALLOWED_ORIGINS` entries.

### ✨ Feature

- Custom HTML 404 for missing / expired / unpublished app subdomains (instead of Django’s plain Not Found page).
- On create/redeploy and delete, forward the caller's identity JWT to register/remove the site origin on identity-service OAuth redirect allowlist (`IDENTITY_SERVICE_URL`) so hosted shells can log in without manual allowlist edits.

### 🐛 Fixed

- App subdomains (`{slug}.shellui.app`) now serve the hosted site for every path, including `/admin`. Django admin / API / docs stay on the apex host only — so React Router refreshes no longer hit Django admin.

### 🔒 Security

- Bump dependencies to clear `pip-audit` findings: Django `6.0.8`, cryptography `50.0.0`, djangorestframework `3.17.2`, requests `2.33.0`, PyJWT `2.13.0`.

### 🏗 Chore

- Add GitHub Actions CI on PRs and `main`/`develop`: Django tests, `uv lock --check`, `pip-audit`, gitleaks, lychee link checks, and Docker build.
- Automate pre-release checklist via `./tools/pre-release-check.sh` and `.github/workflows/pre-release.yml` (PRs to `main`).

## [0.1.0] - 2026-09-03

### 🗑️ Removed

- App compatibility ranges and `GET /hosting/v1/apps/{app}/resolve` — preview hosting always serves the current deployment.

### ✨ Feature

- `ROOT_REDIRECT_URL` — optional permanent (301) redirect for apex `/` (e.g. shellui.app → https://shellui.com); unset keeps the landing page. Hosted app subdomains are unchanged.
- `DELETE /hosting/v1/apps/{ref}` removes a hosted app, deployments, and stored artifacts.
- Preview deploy flow via `POST /hosting/v1/preview` — new slug per deploy, optional slug redeploy, 7-day TTL.
- Public static serving at `https://{site_slug}.shellui.app/` (subdomain per app; local dev uses `/etc/hosts` + `HOSTING_APP_DOMAIN=shellui.local`).
- Deployment finalize extracts `artifact.tar.gz` for browsing; API responses include `urls.url`.
- `approve_hosting_access` management command for local/production waitlist bypass.
- Initial hosting-service Django project with JWT auth, company access waitlist, app/deployment management, and stats API under `/hosting/v1/*`.
- Bootstrap hosting-service from storage-service patterns.
