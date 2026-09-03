# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased]

### 🔒 Security

- Bump dependencies to clear `pip-audit` findings: Django `6.0.8`, cryptography `50.0.0`, djangorestframework `3.17.2`, requests `2.33.0`, PyJWT `2.13.0`.

### 🏗 Chore

- Add GitHub Actions CI on PRs and `main`/`develop`: Django tests, `uv lock --check`, `pip-audit`, gitleaks, lychee link checks, and Docker build.

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
