---
description: How a hosted app and its deployments are created, uploaded, finalized, and rolled back.
---

# Apps and deployments

A hosted app is one site for one company. A deployment is one uploaded build of that app. This page is the lifecycle the API and the Shellui CLI share.

You call the API with `Authorization: Bearer your_access_token_here`. The token comes from identity-service. The company must already be [approved](company-access.md), unless `HOSTING_DEBUG_OPEN=true`.

## Apps

An app row stores a company-scoped `name`, a globally unique public `slug`, a `display_name`, and the current deployment. The slug is generated. It is 12 characters, starts with a letter, and uses lowercase letters and digits. You do not pick it.

Names and slugs are 3 to 63 characters, start with a letter, and contain only lowercase letters, digits, and hyphens. `admin`, `api`, `apps`, `health`, `hosting`, `stats`, `access`, `deployments`, and `preview` are reserved.

Two creates exist:

- `POST /hosting/v1/apps` with `name` and `display_name` creates a named app. `expires_at` stays empty, so the site does not expire. The name must be unique inside the company.
- `POST /hosting/v1/preview` is what `shellui deploy` calls. With no `slug`, it creates a preview app owned by the caller. Finalize later sets `expires_at`.

`GET /hosting/v1/apps` lists the caller's company. `GET` and `DELETE /hosting/v1/apps/{app_ref}` accept the app UUID, the company-scoped name, or the public slug. Delete removes the app, its deployments, the stored files, and the identity OAuth redirect for that origin. It emits `hosting.app.deleted`.

The default limit is 5 apps per company (`HOSTING_MAX_APPS_PER_COMPANY`). Preview creates count sites that have not expired. `POST /hosting/v1/apps` counts every row.

## Deployments

`POST /hosting/v1/apps/{app_ref}/deployments` creates a draft. Body fields `app_version` and `shellui_version` must be semantic versions (`1.4.0`). The optional `pinned` flag is stored and returned. Serving ignores it.

Each app keeps at most `HOSTING_MAX_DEPLOYMENTS_PER_APP` deployment rows (default 20), including ones you no longer serve.

The statuses you will see:

| Status | Meaning |
| --- | --- |
| `draft` | Row exists, no archive yet |
| `uploading` | An archive was stored |
| `active` | This deployment is the one being served |
| `superseded` | It was active, then a newer finalize or a rollback replaced it |
| `failed` | Extract failed. The row stays failed |

`shellui deploy` does not call the deployments collection itself. It calls preview, which creates the draft for you, then uploads and finalizes.

## Upload and finalize

Upload with `PUT /hosting/v1/apps/{app_ref}/deployments/{id}/upload`. The body is the gzip tar archive (`Content-Type: application/gzip`), or a multipart file. The default cap is `100M` (`HOSTING_MAX_UPLOAD_BYTES`). A draft, an in-progress upload, or a failed deployment can accept another upload. An active one cannot.

`POST /hosting/v1/apps/{app_ref}/deployments/{id}/finalize` extracts the archive and, on success, marks this deployment `active`. The previous active deployment becomes `superseded`. The app's `current_deployment` points at the new row. Preview apps get a new `expires_at` of now plus `HOSTING_PREVIEW_TTL_DAYS` (default 7). The in-process serve cache for that slug is cleared.

Extract keeps regular files only, drops path traversal, and enforces three limits: 5000 files, `500M` uncompressed in total, and `100M` for one file. Those are `HOSTING_MAX_EXTRACT_FILES`, `HOSTING_MAX_EXTRACT_BYTES`, and `HOSTING_MAX_EXTRACT_FILE_BYTES`. A bad archive stays `failed`, emits `hosting.deployment.failed`, and does not replace the current site.

Files land at `{HOSTING_KEY_PREFIX}/{app_uuid}/deployments/{deployment_uuid}/artifact.tar.gz`, with the extracted tree under `extracted/`.

## Roll back

`POST /hosting/v1/apps/{app_ref}/deployments/{id}/rollback` makes an older deployment active again. The target must already have an archive and a status of `active`, `superseded`, or `ready`. Current deploys do not write `ready`. Rollback still accepts it. The serve cache is cleared. Rollback does not emit a hosting event and does not extend `expires_at`.

From a Shellui project that has `hosting.slug` set:

```bash
shellui deploy rollback --to 1.2.3
shellui deploy rollback --deployment 660e8400-e29b-41d4-a716-446655440001
```

`--to` matches `app_version`. `shellui deploy history` lists the rows for that slug.

## Events

These catalog events fire from the lifecycle above. Payloads and webhook delivery are in [Webhooks](actions.md).

| Event | When |
| --- | --- |
| `hosting.app.created` | An app row is created |
| `hosting.app.deleted` | An app and its files are removed |
| `hosting.deployment.created` | A draft deployment is created |
| `hosting.deployment.succeeded` | Finalize extracted the archive and activated the deployment |
| `hosting.deployment.failed` | Extract failed |

Succeeded and failed events name the caller who finalized. Created events name the caller who created the row.
