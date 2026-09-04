# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
