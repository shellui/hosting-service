# JWT claim trust (resource server model)

Hosting-service is a **resource server**: it verifies Bearer JWTs issued by identity-service and trusts selected claims for authorization. It does **not** maintain its own user directory or re-query identity on every request.

## Verification boundary

Tokens are verified with RS256 against a pinned JWKS document (`IDENTITY_JWKS_FILE` / `IDENTITY_JWKS`) or, in local dev, fetched from `IDENTITY_JWKS_URL`. Production requires:

- `IDENTITY_ISSUER` — JWT `iss` must match
- `IDENTITY_AUDIENCE` — JWT `aud` must match
- Pinned JWKS (no runtime key fetch)

HS256 fallback (`JWT_HS256_FALLBACK_SECRET`) is dev-only and refused when `DEBUG=false`.

## Privileged claims (H-12)

These claims are read from the JWT payload and **not** re-validated against identity-service on each API call:

| Claim path | Used for |
|------------|----------|
| `user_metadata.is_staff` | Staff-only ops (global metrics, cross-company access updates, stats without company filter) |
| `user_metadata.is_company_owner` | Company metrics, access management visibility |
| `pat_agm` | Global Prometheus metrics via staff-issued PAT |
| `company_id` | Tenant scope for apps, deployments, and metrics |

**Trust model:** hosting-service assumes identity-service correctly embeds these claims at token issuance time. A forged token cannot pass verification without a valid signature from the pinned JWKS.

## Optional re-validation for privileged ops

For high-risk operations (e.g. staff approving waitlist access, global metrics), operators may optionally add an identity-service callback to confirm the caller still holds `is_staff` before acting. Hosting-service does not implement this callback today; privileged gates rely on short-lived JWT expiry and JWKS pinning.

Future hardening paths:

- Introspect or profile-fetch against identity-service for staff-only mutations
- Shorter access-token TTL for staff sessions
- PAT scopes instead of `user_metadata` for automation (already used for `pat_agm`)

## Company scope

Routine hosting APIs enforce `company_id` from the token against row-level ownership (`App.company_id`, etc.). Staff JWTs may omit or override company scope on specific endpoints (stats, access admin).
