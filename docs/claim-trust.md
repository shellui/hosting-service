---
description: How hosting-service verifies identity-service JWTs, and which claims it trusts for staff, owners, and company scope.
---

# JWT and claim trust

hosting-service checks Bearer JWTs from identity-service and reads a few claims for authorization. It does not store users, and it does not call identity-service again on each API request.

Send the token as `Authorization: Bearer your_access_token_here`.

## What gets verified

Tokens must include `exp`. The signature is checked as RS256 against a JSON Web Key Set (JWKS). Pin that document in production with `IDENTITY_JWKS_FILE` or `IDENTITY_JWKS`. Local development can fetch `IDENTITY_JWKS_URL`, which defaults to `{IDENTITY_SERVICE_URL}/.well-known/jwks.json`.

When `DEBUG=false`, the process refuses to start unless all of these are set:

- `IDENTITY_ISSUER`: the JWT `iss` claim must match
- `IDENTITY_AUDIENCE`: the JWT `aud` claim must match
- A pinned JWKS document. A runtime fetch from `IDENTITY_JWKS_URL` is refused

`JWT_HS256_FALLBACK_SECRET` verifies HS256 tokens from a local identity-service debug setup. Set it to that service's `SECRET_KEY`. hosting-service refuses to start with the secret set while `DEBUG=false`, unless `ALLOW_JWT_HS256_FALLBACK=true`.

Issuer and audience checks run only when the matching variable is set. Production always sets both.

## Claims hosting-service trusts

These claims are taken from the verified payload. hosting-service does not ask identity-service whether they are still true on the next request:

| Claim | Used for |
| --- | --- |
| `user_metadata.is_staff` | Staff operations: global metrics, access updates for any company, stats with no company filter |
| `user_metadata.is_company_owner` | Company metrics, and read access to the waitlist for that company |
| `pat_agm` | Global Prometheus metrics for a personal access token (PAT) issued by staff |
| `company_id` | Which company's apps, deployments, and metrics this caller may touch |
| `user_id` or `sub` | Numeric identity user id stored on apps, deployments, and the event log |
| `email` | Actor email on events, when the token carries one |

A forged payload cannot pass unless it is signed by a key in the pinned JWKS. Privileged routes rely on that signature check and on token expiry. hosting-service does not re-fetch the staff flag from identity-service before it acts.

## Company scope

App and deployment routes compare `company_id` on the token with `App.company_id`. You only see your company's rows.

Staff tokens can update hosting access for a `company_id` in the request body, and can read `GET /hosting/v1/stats` with no company filter. Metrics routes reject a `company_id` query parameter. `GET /hosting/v1/metrics` uses the company on the token and requires staff or a company owner. `GET /hosting/v1/metrics/all` requires staff or `pat_agm`.

Shellui Actions routes under `/api/v1/actions/` let staff pass any `company_id` query parameter. Company owners may omit it or pass their own. Another company returns 403.

## Related

- [Configuration](configuration.md) lists the JWT environment variables
- [Security hardening](security-hardening.md) covers production JWT rules
- [Company access](company-access.md) uses `is_staff` and `is_company_owner`
