# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.4.1] - 2026-09-22

### 🛠 Improvements

- Align the shellui.app apex landing with Shellui brand assets and shellui.com design tokens (gray canvas, honey gold primary, system typography).
- Nav: Shellui **mark** (`#logo-shellui-mark`, ~34px, same as shellui.com header); footer brand: Shellui **wordmark** (`#logo-shellui`, 1.25rem height). No domain suffix beside either logo.
- Product links in nav, footer, and Explore: Website, Docs, Playground, GitHub, then **Agents** / shellui.ai last.
- Soft primary hero ambient (shellui.ai blur wrapper + clipped gradient), calmer hierarchy, and monospace only for terminal and command snippets.
- Nav and footer chrome width `64rem` (shellui.ai `max-w-5xl`) with matching horizontal gutters.
- Add Shellui favicons on the apex landing and other public HTML pages (same set as shellui.com / shellui.ai).
- Footer layout aligned with shellui.ai: brand and links on one row, meta line below, foreground wordmark.
- Replace the apex landing inline CSS with Tailwind CSS v4 (`npm run build:css` → `static/css/site.css`), sharing Shellui design tokens with shellui.ai.

## [0.4.0] - 2026-09-18

### 🔒 Security

- Gate public first-run superuser bootstrap at `/`: when the user table is empty and `DEBUG=false`, the web form is hidden and POST returns 403 unless a valid `SETUP_TOKEN` is provided (query param, hidden field, or `X-Setup-Token` header). Prefer `python manage.py createsuperuser` in production (mirrors identity-service).
- **H-11:** `POST /hosting/v1/access` transitions to `approved` or `denied` are staff-only; company owners can no longer self-approve the hosting waitlist.
- **M-28:** `HOSTING_DEBUG_OPEN` is fail-closed — only an explicit truthy env value skips the waitlist (`DEBUG=true` no longer auto-enables bypass).
- **M-01 / M-07 / M-23 / H-12 (#12):** CORS allow-all + `CORS_ALLOW_CREDENTIALS=false` (startup fails on unsafe combo); HSTS and secure cookies when `DEBUG=false`; Postgres `ssl_require` by default with `POSTGRES_SSL_REQUIRE=false` escape; `IDENTITY_ISSUER` / `IDENTITY_AUDIENCE` and pinned JWKS required in production; optional `DJANGO_ADMIN_ENABLED=false`.
- **M-02 (#12):** Cache-backed rate limits on preview/deploy, upload, finalize, rollback, delete, and access-request endpoints.
- **M-25/M-26/M-27:** Tar extract resource caps (max files, total uncompressed bytes, per-file size) with atomic rollback on violation; hardened member path validation (`normpath`, reject `..` components). Static AppServe rejects literal and URL-encoded path traversal before opening storage.

### 📚 Documentation

- Add `./tools/prod-config-check.sh` for post-deploy HTTPS smoke tests of the hosting platform (mirrors identity-service); documented in README and PUBLISH.md.
- README, `.env.example`, and production checklist in `PUBLISH.md` document staff-only approval and explicit `HOSTING_DEBUG_OPEN` opt-in.
- Add `docs/security-hardening.md` (CORS, rate limits, transport, admin isolation, Postgres SSL) and `docs/claim-trust.md` (JWT privileged claims and JWKS pinning).

### 🐛 Bug Fixes

- Pre-release Docker smoke test supplies production identity env (`IDENTITY_ISSUER`, `IDENTITY_AUDIENCE`), disables HTTP SSL redirect for local curls, and dumps container logs when health never becomes ready.

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
