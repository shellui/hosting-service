---
description: How hosting-service verifies identity-service JWTs, and which claims it trusts for staff, owners, and company scope.
---

# JWT and claim trust

hosting-service checks Bearer JWTs from identity-service and reads a few claims for authorization. It does not store users, and it does not call identity-service again on each API request.

Send the token as `Authorization: Bearer your_access_token_here`.

## What gets verified

Tokens must include `exp`. The signature is checked as RS256 against a JSON Web Key Set (JWKS). The token `kid` header must name a key in that set. An unknown or missing `kid` is rejected, including when the set contains one key.

In production, hosting-service fetches JWKS from `IDENTITY_JWKS_URL`, or from `{IDENTITY_SERVICE_URL}/.well-known/jwks.json` when that URL is not set. Pinning with `IDENTITY_JWKS_FILE` or `IDENTITY_JWKS` is optional and wins over a fetch when set.

When `DEBUG=false`, the process refuses to start unless all of these are set:

- `IDENTITY_ISSUER`: the JWT `iss` claim must match
- `IDENTITY_AUDIENCE`: the JWT `aud` claim must match
- At least one JWKS source: `IDENTITY_JWKS_FILE`, `IDENTITY_JWKS`, `IDENTITY_JWKS_URL`, or `IDENTITY_SERVICE_URL` (the service does not fall back to localhost in production)

`JWT_HS256_FALLBACK_SECRET` verifies HS256 tokens from a local identity-service debug setup. Set it to that service's `SECRET_KEY`. hosting-service refuses to start with the secret set while `DEBUG=false`, unless `ALLOW_JWT_HS256_FALLBACK=true`.

Issuer and audience checks run only when the matching variable is set. Production always sets both.

## Claims hosting-service trusts

These claims are taken from the verified payload. hosting-service does not ask identity-service whether they are still true on the next request:

| Claim | Used for |
| --- | --- |
| `user_metadata.is_staff` | Staff operations: access updates for any company, stats with no company filter |
| `user_metadata.is_company_owner` | Read access to the waitlist for that company |
| `company_id` | Which company's apps and deployments this caller may touch |
| `user_id` or `sub` | Numeric identity user id stored on apps, deployments, and the event log |
| `email` | Actor email on events, when the token carries one |

A forged payload cannot pass unless it is signed by a key in the configured JWKS. Privileged routes rely on that signature check and on token expiry. hosting-service does not re-fetch the staff flag from identity-service before it acts.

## Agent access tokens

Identity agent access tokens use `sub` `agent:{id}` and are accepted on `POST /mcp`. The filesystem artifact upload PUT that Shellui MCP returns also accepts that bearer. Other REST routes refuse it.

| Claim | Used for |
| --- | --- |
| `owner_user_id` | Regional user id of the member who approved the agent. Omitted when there is no user. This is not a company-owner flag |
| `mcp_access` | `read_only`, `ask`, or `full`. Missing means read-only |
| `company_id` | Company scope. The agent cannot switch company |
| `token_type` | `access` is accepted. `refresh` is refused as a bearer |

The principal is never staff and never a company owner, including when `user_metadata` says otherwise.

## Company scope

App and deployment routes compare `company_id` on the token with `App.company_id`. You only see your company's rows.

Staff tokens can update hosting access for a `company_id` in the request body, and can read `GET /hosting/v1/stats` with no company filter. hosting-service ignores a `pat_agm` claim. It does not store that claim.

Shellui Actions routes under `/api/v1/actions/` let staff pass any `company_id` query parameter. Company owners may omit it or pass their own. Another company returns 403.

## Related

- [Configuration](configuration.md) lists the JWT environment variables
- [Security hardening](security-hardening.md) covers production JWT rules
- [Company access](company-access.md) uses `is_staff` and `is_company_owner`
