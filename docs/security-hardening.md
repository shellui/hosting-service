# Security hardening (hosting-service)

Production deployments should configure the controls below. Defaults follow `DEBUG=false` unless noted.

## CORS (browser API calls)

Shellui customer shells run on unknown domains and call `/hosting/v1/*` from the browser with a Bearer JWT in the `Authorization` header. A static `CORS_ALLOWED_ORIGINS` list does not scale for multi-tenant hosting previews.

**Default (recommended):** `CORS_ALLOW_ALL_ORIGINS=true` with `CORS_ALLOW_CREDENTIALS=false`. API auth is Bearer JWT, not cookies — permissive CORS is intentional (Supabase-style).

**Token delivery** after OAuth login is **not** governed by CORS. Identity-service `CompanyOAuthRedirect` remains the strict boundary for redirect targets.

**Lock-down (optional):** set `CORS_ALLOW_ALL_ORIGINS=false` and list first-party origins in `CORS_ALLOWED_ORIGINS`.

**Blocked at startup:** `CORS_ALLOW_ALL_ORIGINS=true` with `CORS_ALLOW_CREDENTIALS=true` — wildcard origins cannot safely carry credentials.

## Rate limiting

Cache-backed limits apply to abuse-prone hosting endpoints (per authenticated user, falling back to client IP):

| Scope | Default | Endpoints |
|-------|---------|-----------|
| `deploy` | 30/min | `POST /hosting/v1/preview`, `POST …/deployments`, finalize, rollback |
| `upload` | 20/min | `PUT …/deployments/{id}/upload` |
| `destructive` | 10/min | `DELETE /hosting/v1/apps/{ref}` |
| `access_request` | 10 per 5 min | `POST /hosting/v1/access/request` |

Tune with `HOSTING_RATE_LIMIT_*` env vars or set `HOSTING_RATE_LIMIT_ENABLED=false` to disable (not recommended in production).

## Waitlist bypass (`HOSTING_DEBUG_OPEN`)

Fail-closed: only an explicit truthy env value skips the company waitlist. `DEBUG=true` does **not** auto-enable bypass.

**Blocked at startup:** `HOSTING_DEBUG_OPEN=true` when `DEBUG=false`.

## JWT verification (production)

When `DEBUG=false`:

- `IDENTITY_ISSUER` and `IDENTITY_AUDIENCE` are **required** (iss/aud validation).
- JWKS must be **pinned** via `IDENTITY_JWKS_FILE` or `IDENTITY_JWKS`. Runtime fetch from `IDENTITY_JWKS_URL` is for local/dev only.

See [claim-trust.md](claim-trust.md) for privileged JWT claims (`is_staff`, `is_company_owner`, `pat_agm`).

## HTTPS, HSTS, and secure cookies

When `DEBUG=false`:

- `SECURE_SSL_REDIRECT=true` — redirect HTTP to HTTPS (disable only behind TLS-terminating proxies that handle redirects)
- `SECURE_HSTS_SECONDS=31536000` (1 year)
- `SESSION_COOKIE_SECURE=true`, `CSRF_COOKIE_SECURE=true`

Override any flag via env (see `.env.example`).

## Postgres SSL

When `POSTGRES_DATABASE_URL` is set and `DEBUG=false`, connections use `ssl_require=true` by default. Set `POSTGRES_SSL_REQUIRE=false` only for local Postgres without TLS (e.g. Coolify internal DB on a private network).

## Django admin isolation

The Django admin UI is cross-tenant (local Django users, not JWT company scope). Operational controls:

- **Network lock:** expose `/admin/` only on an internal hostname or VPN; do not publish it on the public hosting apex.
- **MFA:** enforce MFA on admin accounts at the identity / SSO layer where staff authenticate.
- **Disable when unused:** set `DJANGO_ADMIN_ENABLED=false` to remove admin routes entirely.

## Trusted proxies and client IP

Rate limits derive client IP from `REMOTE_ADDR` unless the direct peer is listed in `TRUSTED_PROXY_IPS` (comma-separated IPs or CIDRs). When trusted, the first hop of `X-Forwarded-For` is used.

Example (nginx on the same host):

```bash
TRUSTED_PROXY_IPS=127.0.0.1,::1
```

Without trusted proxies, clients cannot spoof IPs by sending `X-Forwarded-For` directly.
