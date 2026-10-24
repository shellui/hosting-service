# hosting-service

Deploys and serves Shellui apps, one subdomain per site.

[![CI](https://github.com/shellui/hosting-service/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/shellui/hosting-service/actions/workflows/ci.yml)
[![Docker Hub](https://img.shields.io/docker/v/shellui/hosting-service?sort=semver&label=docker)](https://hub.docker.com/r/shellui/hosting-service)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

hosting-service is what `shellui deploy` talks to. It takes a build of your shell through the `/hosting/v1/*` API, stores it on S3 or the filesystem, and serves it at `https://{slug}.{HOSTING_APP_DOMAIN}/`. It verifies JWTs from [identity-service](https://github.com/shellui/identity-service) and registers each site on the company OAuth redirect allowlist, so sign-in works on a fresh preview.

## Get started

You need Docker and Git, and an [identity-service](https://github.com/shellui/identity-service) running on port 8000.

```bash
git clone https://github.com/shellui/hosting-service.git
cd hosting-service
cp .env.example .env   # then set SECRET_KEY
docker compose up --build
```

The API runs on [http://localhost:8002](http://localhost:8002). `/api/docs/` is the OpenAPI reference and `/admin/` is Django admin.

Then deploy from any Shellui project with `hosting.url` set to `http://localhost:8002`:

```bash
shellui login
shellui deploy --build
```

The CLI prints the site URL, its slug and its expiry. Local sites live on `{slug}.shellui.local`, so add the slug to `/etc/hosts`. The full path, including company approval, is in [Run hosting-service](docs/getting-started.md).

## Configuration

For production, `python manage.py generate_env --host hosting.example.com` prints the required settings with a fresh `SECRET_KEY`.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Django secret, 50+ characters when `DEBUG=false` |
| `HOSTING_APP_DOMAIN` | Apps domain, for example `shellui.app` or `eu.shellui.app` |
| `IDENTITY_JWKS` | Pinned identity public keys, required in production |
| `IDENTITY_ISSUER`, `IDENTITY_AUDIENCE` | Must match identity `JWT_ISSUER` and `JWT_AUDIENCE` |
| `REDIS_URL` | Required when `DEBUG=false`. Rate limits and scheduled jobs |

Every setting is in [Configuration](docs/configuration.md).

## Documentation

The handbook lives in [`docs/`](docs/index.md) and is published at [docs.shellui.com/hosting](https://docs.shellui.com/hosting).

- [Apps and deployments](docs/apps-and-deployments.md) and [preview URLs and serving](docs/preview-and-serving.md)
- [Company access](docs/company-access.md) and [JWT claim trust](docs/claim-trust.md)
- [Webhooks](docs/actions.md), [email](docs/email.md), [event log](docs/event-log.md) and [maintenance jobs](docs/maintenance-jobs.md)
- [Security hardening](docs/security-hardening.md) and the [API](docs/api.md)

## Development

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py runserver 8002
uv run python manage.py test
```

Run `npm run watch:css` in a second terminal when you edit the landing page templates. To preview the docs site, clone [shellui/shellui](https://github.com/shellui/shellui) next to this repository and run `DOCS_SERVICES=hosting pnpm docs:start` there.

Releases go to Docker Hub as `shellui/hosting-service`. The checklist is in [PUBLISH.md](PUBLISH.md) and changes are in [CHANGELOG.md](CHANGELOG.md).

## Contributing

Open an issue or a pull request against `develop`. CI runs the tests, a dependency audit, a secret scan, a link check and the docs build. Coding agents start with [AGENTS.md](AGENTS.md).

## Shellui projects

| Project | What it does |
| --- | --- |
| [shellui](https://github.com/shellui/shellui) | The shell, CLI and SDK |
| [admin](https://github.com/shellui/admin) | Administration app inside the shell |
| [files](https://github.com/shellui/files) | File explorer for storage-service |
| [identity-service](https://github.com/shellui/identity-service) | Sign-in, companies and tokens |
| [storage-service](https://github.com/shellui/storage-service) | File storage |
| [hosting-service](https://github.com/shellui/hosting-service) | Deploys and serves Shellui apps |
| [email-service](https://github.com/shellui/email-service) | Templates and sends email |
| [skills](https://github.com/shellui/skills) | Agent Skills for coding agents |
| [playground](https://github.com/shellui/playground) | Live demo of the shell |

## License

[MIT](LICENSE)
