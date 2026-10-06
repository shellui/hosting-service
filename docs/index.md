# hosting-service documentation

hosting-service is the Shellui backend that hosts microfrontend apps. It has a deployment API under `/hosting/v1/*` and serves each deployed site at `https://{slug}.{HOSTING_APP_DOMAIN}/`.

It checks JWTs issued by [identity-service](https://github.com/shellui/identity-service) and stores deployment archives in S3 or on the local filesystem. You deploy with the Shellui CLI (`shellui deploy --build`). Each deploy creates a preview site with its own slug, which expires after 7 days by default (`HOSTING_PREVIEW_TTL_DAYS`). Deploying to the same slug again resets the timer.

## Pages

| Page | What it covers |
| ---- | -------------- |
| [Configuration](configuration.md) | Environment variables for the Redis cache and the Gunicorn workers in the Docker image |
| [Security hardening](security-hardening.md) | CORS, rate limits, JWT checks, HTTPS, Postgres SSL, admin isolation, and trusted proxies |
| [JWT claim trust](claim-trust.md) | How hosting-service verifies identity-service tokens and which claims it trusts |
| [Shellui webhooks](actions.md) | Webhook rules for `hosting.*` events, the admin API, and retries with `retry_webhooks` |
| [n8n](n8n.md) | Receive hosting webhooks in an n8n workflow and verify their signature |
| [Event log](event-log.md) | Every hosting event in one table, how long it is kept, and the hourly purge job |

## More

- Local setup, endpoints, and Docker: [README](https://github.com/shellui/hosting-service/blob/develop/README.md) on GitHub.
- Releases and production checks: [PUBLISH.md](https://github.com/shellui/hosting-service/blob/develop/PUBLISH.md) on GitHub.
- These pages are published at [docs.shellui.com/hosting](https://docs.shellui.com/hosting) by [shellui/shellui](https://github.com/shellui/shellui).
