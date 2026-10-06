---
description: How preview slugs become public URLs, how long a preview stays up, and how login redirects are registered.
---

# Preview sites and public URLs

A preview is a hosted app with an expiry. Visitors open it on a hostname whose first label is the site slug. This page is how that hostname is chosen, cached, and tied to identity-service login.

The deployment steps are in [Apps and deployments](apps-and-deployments.md).

## The URL the API returns

Browse links use `HOSTING_APP_SCHEME` and `HOSTING_APP_DOMAIN`:

```text
https://vpzzsxvzsmp7.shellui.app/
```

Locally that is `http://vpzzsxvzsmp7.shellui.local:8002/` when the dev server listens on 8002. The link is built by the API. It is not the only hostname the process will serve.

## Which host is an app

The first label of the `Host` header is the slug when all of these are true:

- The hostname has at least three labels (`slug.shellui.app`, not `shellui.app`)
- It is not an IP address
- It is not `localhost` or the Django test hostname
- The first label is not `www`, `hosting`, `api`, or `admin`

`shellui.app` and `localhost:8002` stay on the platform: landing page, `/hosting/v1/`, `/admin/`, `/api/docs/`, and `/llms.txt`. On an app host, every path is the hosted site, including `/admin`. That keeps a single-page app refresh on a client route from opening Django admin.

Django still has to allow the `Host` value. With `DEBUG=true`, `HOSTING_ALLOW_ANY_HOST` defaults to on and `ALLOWED_HOSTS` includes `*`. In production the service adds `.{HOSTING_APP_DOMAIN}` to `ALLOWED_HOSTS`. A custom parent domain needs its own `ALLOWED_HOSTS` entry.

## What the visitor receives

The response is the extracted files of `current_deployment`, when that deployment is `active`. Missing HTML routes fall through to `index.html` so client-side routers survive a refresh. Missing static assets (`.js`, `.css`, images, fonts, and the other extensions the server treats as files) stay a hard 404.

Cache headers:

| Response | `Cache-Control` |
| --- | --- |
| HTML | `no-cache` |
| Content-hashed file, such as `main-D9ih21to.js` | `public, max-age=31536000, immutable` |
| Other static files | `public, max-age=86400` |

Responses omit `X-Frame-Options`, so a Shellui shell can embed the site in an iframe.

Slug lookups are cached in the worker process for `HOSTING_SERVE_CACHE_TTL_SECONDS` (default 45). Set `0` to disable the cache. Finalize and rollback clear that slug immediately. The cache is not Redis, and it is not shared across Gunicorn workers.

## Expiry

Preview apps record the creating user. The first successful finalize sets `expires_at` to now plus `HOSTING_PREVIEW_TTL_DAYS` (default 7). Each later successful finalize on that app resets the timer. `POST /hosting/v1/apps/{app_ref}/renew-expiry` resets it too, but only while the site has not expired yet.

After `expires_at`, the hostname returns a 404 page that says the site has expired. The app row and files are still stored. `renew-expiry` then returns 409 `preview_expired`. Deploy again to the same slug: preview prepare still finds an app you own, and a successful finalize sets a new `expires_at`.

Apps created with `POST /hosting/v1/apps` leave `expires_at` empty. Those sites do not expire.

A preview slug can be redeployed only by its company, and only by the account in `created_by_id` when that field is set. Another company gets 403.

## Login on the hosted origin

If `IDENTITY_SERVICE_URL` is set, hosting-service forwards the caller's JWT to identity-service:

- `PUT {IDENTITY_SERVICE_URL}/api/v1/hosting-oauth-redirects` on create and on redeploy
- A delete of that origin when the app is deleted

The body is the origin (`https://vpzzsxvzsmp7.shellui.app`, no path) and a label. The call is best-effort. A failure is logged and does not roll back the deploy. Nothing is sent when the identity URL or the caller token is missing. The allowlist controls where identity-service may send the browser after login. It is not the hosting API CORS list. CORS is covered in [Security hardening](security-hardening.md).
