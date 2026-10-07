---
description: Where the OpenAPI docs are served, and the route groups under /hosting/v1/ and /api/v1/actions/.
---

# API reference

Each running hosting-service serves its own HTTP reference. This page lists where that reference lives and groups the routes. Request and response fields are on the live schema, which matches the code you deployed.

## Interactive docs

| Page | Path |
| --- | --- |
| Swagger UI | `/api/docs/` |
| ReDoc | `/api/docs/redoc/` |
| OpenAPI schema | `/api/schema/` |

Open Swagger from Django admin and the session access token is applied for you. Otherwise choose **Authorize** and paste `Bearer your_access_token_here`, or the raw JWT.

`GET /hosting/v1/health` does not require a token. It returns `status`, `version`, the artifact backend, and which JWKS source is in use. Every other `/hosting/v1/` route expects `Authorization: Bearer your_access_token_here` from identity-service.

## Route groups

Paths below are relative to the apex host, for example `http://localhost:8002`. App subdomains do not serve these routes. They serve the hosted site.

| Group | Paths |
| --- | --- |
| Health | `GET /hosting/v1/health` |
| Access | `GET` and `POST /hosting/v1/access`, `POST /hosting/v1/access/request` |
| Preview | `POST /hosting/v1/preview` |
| Apps | `GET` and `POST /hosting/v1/apps`, `GET` and `DELETE /hosting/v1/apps/{app_ref}`, `POST /hosting/v1/apps/{app_ref}/renew-expiry` |
| Deployments | `GET` and `POST /hosting/v1/apps/{app_ref}/deployments` |
| Upload | `PUT /hosting/v1/apps/{app_ref}/deployments/{id}/upload` |
| Finalize and rollback | `POST /hosting/v1/apps/{app_ref}/deployments/{id}/finalize`, same path with `/rollback` |
| Stats | `GET /hosting/v1/stats` |
| Metrics | `GET /hosting/v1/metrics`, `GET /hosting/v1/metrics/all` |
| Shellui Actions | `/api/v1/actions/events`, `/rules`, `/deliveries` |
| Event log | `GET /api/v1/actions/event-log` |

`{app_ref}` is an app UUID, a company-scoped name, or a public slug. `{id}` on a deployment is a UUID.

## Who can call them

Company members with `company_id` in the token can list and deploy their company's apps, after the waitlist says `approved`. See [Company access](company-access.md) and [Apps and deployments](apps-and-deployments.md).

| Route | Who |
| --- | --- |
| `GET /hosting/v1/stats` | The caller's company. Staff may omit the company and receive every company |
| `GET /hosting/v1/metrics` | Staff or a company owner. Company id comes from the token. A `company_id` query parameter is 400 |
| `GET /hosting/v1/metrics/all` | Staff, or a personal access token with the `pat_agm` claim |
| `/api/v1/actions/*` | Staff, or a company owner scoped to the token `company_id` |

Metrics responses are Prometheus text, not JSON. The gauge names start with `shellui_hosting_`.

Error JSON uses `statusCode`, `error`, and `message`. Hosting responses include `X-Request-ID`.
