---
title: hosting-service
sidebar_label: Overview
description: hosting-service stores Shellui app builds and serves each one on a public URL. This page is the map of the handbook.
---

# hosting-service

hosting-service stores Shellui app builds and serves each one on a public URL. You deploy a static build, then open it in a browser. The deployment API lives under `/hosting/v1/`.

## What hosting-service is

hosting-service is the Shellui backend that hosts microfrontend apps. It accepts a gzip tar archive, extracts the files, and serves that build as a static site. The same process serves the API, Django admin, and OpenAPI on the apex host.

It is a Django app, published as the `shellui/hosting-service` Docker image. It checks JSON Web Tokens (JWTs) issued by identity-service. It does not sign people in itself.

## Who it is for

Use it when a Shellui app needs a published preview. Company owners deploy with the Shellui CLI. Staff decide which companies may host. Operators run the process, the database, and Redis.

Your product stays in the shell. hosting-service does not replace identity-service, storage-service, or email-service.

## What it stores and serves

Each hosted app belongs to one company. The app has a company-scoped name and a public slug used in the hostname. A deployment is one uploaded build: app version, Shellui version, status, and the archive.

The archive is stored as `artifact.tar.gz`, then extracted for serving. The default backend is the local filesystem. Set `HOSTING_BACKEND=s3` to use an S3-compatible bucket.

Visitors receive the files of the active deployment. HTML responses use `Cache-Control: no-cache`. Content-hashed assets such as `main-D9ih21to.js` are cached for a year.

## How it fits with identity, storage, and email

identity-service signs people in and issues the Bearer JWT you send on API calls. hosting-service has no user table. When `IDENTITY_SERVICE_URL` is set, creating, redeploying, or deleting an app registers that origin on the company OAuth redirect allowlist, so the hosted app can finish login.

storage-service is a separate file API. Deployment archives stay in the hosting filesystem or in the hosting bucket. hosting-service does not call storage-service.

hosting-service does not compose mail. When `EMAIL_SERVICE_API_KEY` is set, each hosting event is forwarded to email-service, and a company rule there decides whether to send. Company owners can also attach an HTTPS endpoint with a Shellui Actions webhook. Every event is stored in the event log.

## Deploy and browse flow

`shellui deploy` calls `POST /hosting/v1/preview`, uploads the archive, then finalizes it:

1. With no `hosting.slug`, hosting-service creates an app and a 12-character public slug.
2. It creates a draft deployment. The CLI uploads `artifact.tar.gz`.
3. Finalize extracts the archive, marks that deployment active, and points the app at it.
4. The CLI prints a browse URL, for example `https://vpzzsxvzsmp7.shellui.app/`.

Set `hosting.slug` to publish another build to a site you already own. A successful finalize resets the preview timer (`HOSTING_PREVIEW_TTL_DAYS`, default 7).

The API and the public site share one process. A hostname whose first label is the slug serves the app on every path. The apex host serves `/hosting/v1/`, `/admin/`, and `/api/docs/`.

## Access and tenancy

A company must be approved before it can create apps. Owners request access with `POST /hosting/v1/access/request`. Staff approve or deny that request. Set `HOSTING_DEBUG_OPEN=true` to skip the gate locally. That setting is refused when `DEBUG=false`.

Routine API calls use `company_id` from the JWT, so you only see that company's apps. Staff can update access for another company and can read stats without a company filter.

## Webhooks, event log, and email

Creating or deleting an app, and creating, finishing, or failing a deployment, writes an event. Matching Shellui Actions webhook rules receive a signed POST. Delivery is at-least-once. `manage.py retry_webhooks` retries failures. There is no separate actions service.

The same command retries the email-service forward. That body omits sign-in links, tokens, and secret-shaped fields. Webhook envelopes omit the same fields. See [Email notifications](email.md).

The event log keeps those events, including the acting user, for `EVENT_LOG_RETENTION_DAYS` (default 7).

## Configure and run

Copy [`.env.example`](../.env.example) to `.env`, point `IDENTITY_SERVICE_URL` at identity-service, and run migrations. Docker Compose is the local path in [Run hosting-service](getting-started.md).

The container runs database migrations, then Gunicorn and a Celery worker with beat. `retry_webhooks` runs every minute. `purge_expired_data` runs every hour at minute 17. Redis is required when `DEBUG=false` (`REDIS_URL`). With `DEBUG=true` and no Redis, the web app still starts and the scheduler stays off. See [Scheduled jobs](maintenance-jobs.md).

## Where to go next

Pick the row that matches what you are doing:

| You want to | Start with |
| --- | --- |
| Run it locally | [Run hosting-service](getting-started.md) |
| Set environment variables | [Configuration](configuration.md) |
| Follow an app from upload to active | [Apps and deployments](apps-and-deployments.md) |
| See how public URLs are chosen | [Preview sites and public URLs](preview-and-serving.md) |
| Approve a company | [Company access](company-access.md) |
| See which JWT claims are trusted | [JWT and claim trust](claim-trust.md) |
| Call an HTTPS endpoint on deploy | [Webhooks](actions.md) and [n8n](n8n.md) |
| Forward an event to email-service | [Email notifications](email.md) |
| Read past hosting events | [Event log](event-log.md) |
| Lock down a production install | [Security hardening](security-hardening.md) |
| See how retries and retention run | [Scheduled jobs](maintenance-jobs.md) |
| Browse the HTTP API | [API reference](api.md) |

Source and the changelog are on [GitHub](https://github.com/shellui/hosting-service). These pages are built from `docs/` by [shellui/shellui](https://github.com/shellui/shellui) and published on [docs.shellui.com](https://docs.shellui.com) at `docs.shellui.com/hosting`.
