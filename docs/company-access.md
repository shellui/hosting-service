---
description: Request hosting for a company, approve or deny the waitlist, and see who can skip the gate.
---

# Company access and the waitlist

A company needs an approved hosting row before it can create apps or deployments. This page is that waitlist: who requests, who approves, and how local development skips it.

Access is stored in `CompanyHostingAccess`, one row per identity-service `company_id`. Status is `pending`, `approved`, or `denied`.

## Request access

Any authenticated caller with a `company_id` claim can request access:

```http
POST /hosting/v1/access/request
Authorization: Bearer your_access_token_here
```

The call creates a `pending` row, or moves a `denied` row back to `pending`. It does not change a row that is already `approved` or `pending`. The route is rate limited (`HOSTING_RATE_LIMIT_ACCESS_REQUEST`, default 10 per 300s).

Until the row is `approved`, create and deploy return 403 `hosting_access_denied`.

## Read and decide

`GET /hosting/v1/access` and `POST /hosting/v1/access` require a staff user or a company owner.

`GET` returns the caller's company. The body includes `status`, request and review timestamps, user ids, and `notes`. A company with no row comes back as `status: none`.

`POST` sends JSON:

```json
{
  "status": "approved",
  "notes": "Ready for previews"
}
```

`status` is `pending`, `approved`, or `denied`. Only staff can set `approved` or `denied`. Company owners cannot approve themselves. Staff may pass `company_id` to update a different company. Everyone else is limited to the `company_id` in the token.

From a shell on the server, approve by company id:

```bash
python manage.py approve_hosting_access 1
python manage.py approve_hosting_access 1 --notes "Approved for the docs site"
```

The command creates the row if needed. It prints a warning when the company is already approved. This is a manual step, not a cron job.

## Local bypass

`HOSTING_DEBUG_OPEN=true` skips `assert_hosting_access` for every company. The default is off. `DEBUG=true` does not enable it. [`.env.example`](../.env.example) sets it to `true` so a fresh clone can deploy.

The process refuses to start when `HOSTING_DEBUG_OPEN=true` and `DEBUG=false`. Leave the bypass unset in production and approve companies explicitly.

## Who can do what

| Caller | Request | Read status | Approve or deny |
| --- | --- | --- | --- |
| Signed-in company member | Yes | No | No |
| Company owner | Yes | Yes, own company | No |
| Staff | Yes | Yes | Yes, any `company_id` |

Staff flags come from the JWT. See [JWT and claim trust](claim-trust.md).
