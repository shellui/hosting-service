---
description: Production controls for CORS, rate limits, JWT checks, HTTPS, Postgres, admin, and client IP.
---

# Security hardening

Set the controls on this page before you expose hosting-service beyond a local machine. Defaults below follow `DEBUG=false` unless a row says otherwise. Variable names and defaults are also in [Configuration](configuration.md).

## CORS for browser API calls

Customer shells run on hostnames you do not list in advance, and they call `/hosting/v1/*` with a Bearer JWT. A fixed `CORS_ALLOWED_ORIGINS` list does not cover those previews.

Leave `CORS_ALLOW_ALL_ORIGINS=true` and `CORS_ALLOW_CREDENTIALS=false`. Auth is the Bearer JWT, not a cookie, so the API allows every origin and refuses credentials.

Token delivery after OAuth login is not governed by CORS. The identity-service redirect allowlist is the boundary for where the browser may return. hosting-service can register preview origins on that list. See [Preview sites and public URLs](preview-and-serving.md).

To lock the API to known origins, set `CORS_ALLOW_ALL_ORIGINS=false` and list them in `CORS_ALLOWED_ORIGINS`.

Startup fails when `CORS_ALLOW_ALL_ORIGINS=true` and `CORS_ALLOW_CREDENTIALS=true`. Wildcard origins cannot carry credentials safely.

## Rate limiting

Cache-backed limits apply per authenticated user, then per client IP:

| Scope | Default | Endpoints |
| --- | --- | --- |
| `deploy` | 30 per 60s | `POST /hosting/v1/preview`, create deployment, finalize, rollback |
| `upload` | 20 per 60s | `PUT /hosting/v1/apps/{app_ref}/deployments/{id}/upload` |
| `destructive` | 10 per 60s | `DELETE /hosting/v1/apps/{app_ref}` |
| `access_request` | 10 per 300s | `POST /hosting/v1/access/request` |

Tune them with `HOSTING_RATE_LIMIT_DEPLOY`, `HOSTING_RATE_LIMIT_UPLOAD`, `HOSTING_RATE_LIMIT_DESTRUCTIVE`, and `HOSTING_RATE_LIMIT_ACCESS_REQUEST`. `HOSTING_RATE_LIMIT_ENABLED=false` turns the limits off. Leave them on in production.

The cache is Redis when `REDIS_URL` is set. When `DEBUG=false`, `REDIS_URL` is required: `manage.py check --deploy` reports `authapi.E004` and the container exits if it is missing. Docker defaults to `GUNICORN_WORKERS=2`. Without Redis, each worker would count rate limits on its own, which is why production does not start that way. `authapi.W001` is the same LocMem warning for a multi-worker process that has not reached the hard check.

## Waitlist bypass

Only an explicit truthy `HOSTING_DEBUG_OPEN` skips the company waitlist. `DEBUG=true` does not. Startup fails when `HOSTING_DEBUG_OPEN=true` and `DEBUG=false`. See [Company access](company-access.md).

## JWT verification in production

When `DEBUG=false`:

- `IDENTITY_ISSUER` and `IDENTITY_AUDIENCE` are required, and `iss` / `aud` are checked
- The JWKS document must be pinned with `IDENTITY_JWKS_FILE` or `IDENTITY_JWKS`. Fetching `IDENTITY_JWKS_URL` at runtime is for local development

Privileged claims are listed in [JWT and claim trust](claim-trust.md).

## HTTPS, HSTS, and cookies

When `DEBUG=false`:

- `SECURE_SSL_REDIRECT=true` redirects HTTP to HTTPS. Turn it off only behind a TLS terminator that already redirects
- `SECURE_HSTS_SECONDS=31536000` (1 year), including subdomains
- `SESSION_COOKIE_SECURE=true` and `CSRF_COOKIE_SECURE=true`

Override any of these in the environment. See [`.env.example`](../.env.example).

## Postgres SSL

When `POSTGRES_DATABASE_URL` is set and `DEBUG=false`, connections use TLS (`ssl_require=true`). Set `POSTGRES_SSL_REQUIRE=false` only for a database without TLS on a private network, such as a Coolify internal database.

## Django admin

Django admin is cross-tenant. It uses local Django users, not the JWT company scope.

- Expose `/admin/` on an internal hostname or a VPN, not on the public apex
- Require MFA for staff at the identity provider that signs them into admin
- Set `DJANGO_ADMIN_ENABLED=false` to remove the admin routes when you do not use them

## Trusted proxies and client IP

Rate limits use `REMOTE_ADDR` unless the direct peer is listed in `TRUSTED_PROXY_IPS` (comma-separated IPs or CIDR ranges). When the peer is trusted, the service walks `X-Forwarded-For` from the right, skips hops that match the list, and uses the first untrusted address. A client-supplied leftmost value is ignored when your proxy appends the real chain.

Nginx on the same host:

```bash
TRUSTED_PROXY_IPS=127.0.0.1,::1
```

A private load-balancer subnet:

```bash
TRUSTED_PROXY_IPS=10.0.0.0/8
```

For Coolify or Traefik in front of Gunicorn, list the proxy address or ingress subnet. `REMOTE_ADDR` is then the proxy, and the client IP is the rightmost untrusted hop.

With an empty list, `X-Forwarded-For` from the client is ignored and the app uses `REMOTE_ADDR`.

IPv6 rate-limit keys use the /64 prefix. Logs keep the full address.

## Access logs and error reports

Gunicorn writes an access line with the method and the path. The line omits the query string and the Referer header, so `/?setup_token=…` is not copied to stdout.

When `SENTRY_DSN` is set, events omit stack locals, request bodies, and cookies. Authorization, Cookie, and Referer headers are removed. Query strings are removed from the request URL before the event is sent.

## Email-service URLs

`EMAIL_SERVICE_URL` is checked the same way as a Shellui Actions webhook URL. A private, loopback, or link-local address is refused unless `EMAIL_SERVICE_ALLOW_PRIVATE=true`. The POST does not follow redirects. The service key is not written to the outbox or to logs.
