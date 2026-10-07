---
description: Receive hosting webhooks in n8n, verify the signature, and handle retries.
---

# Using Shellui webhooks with n8n

Shellui hosting can POST signed JSON to an n8n **Webhook** node when a hosting event fires. The signing format matches identity-service and storage-service Shellui Actions.

Webhook rules do not send mail. Mail is a separate forward to email-service, described in [Email notifications](email.md), and it uses the same `retry_webhooks` command.

## Checklist

1. Add a **Webhook** node (POST). Set **Respond** to **Immediately** so Shellui gets a 2xx before the workflow finishes.
2. Copy the **Production URL**, or the **Test URL** while you are building. Activate the workflow before you use the production URL.
3. In Shellui admin, create a Shellui Actions rule: event type, webhook URL, and signing secret (`whsec_…` or plain text).
4. Optional: set **Authorization** on the rule when the node uses Header Auth or Basic Auth.
5. Verify the signature on the raw body. Dedupe on `webhook-id`. That id stays the same across retries.
6. Use **Send test event** in admin while n8n is on **Listen for test event**.

The default timeout is 5s (`ACTIONS_WEBHOOK_TIMEOUT_SECONDS`). Respond immediately in n8n so the first attempt fits in that budget.

## Webhook node setup

| Setting | Value |
| --- | --- |
| HTTP Method | POST |
| Path | Default or custom |
| Respond | **Immediately** |
| Authentication | None on the node if you verify HMAC in a Code node. Or use **Header Auth** / **Basic Auth** and paste the same value into the rule **Authorization** field |

n8n shows a test URL while the editor listens once. **Send test event** works with that URL when n8n is listening. For live hosting events, activate the workflow and use the production URL.

An inactive workflow, or a test URL that is not listening, returns HTTP 404. Shellui treats 404 as retryable, the same as an offline endpoint. Activate the workflow or fix the URL, then use the delivery log and **Requeue**.

## Signing secret format

Shellui accepts two secret forms:

- **Standard Webhooks:** `whsec_` plus base64-encoded random bytes. Use 32 random bytes. Shellui decodes the suffix and uses those bytes as the HMAC key.
- **Plain text:** any string. The UTF-8 bytes are the HMAC key.

Generate a compatible secret in the hosting-service environment:

```python
from apps.actions.webhook_signing import generate_webhook_signing_secret
print(generate_webhook_signing_secret())
```

Shellui generates a `whsec_` secret when you create a rule without one. The create and rotate-secret responses return the full `secret` once. Later reads expose `has_secret` and `secret_hint` (the last four characters) only.

The reference verifier is [verify-shellui-webhook.mjs](examples/verify-shellui-webhook.mjs). Run it with Node.js. Store the same secret in n8n and on the Shellui Actions rule.

## Request headers

| Header | Meaning |
| --- | --- |
| `Content-Type` | `application/json; charset=utf-8` |
| `webhook-id` | Same as envelope `id`. Stable across retries |
| `webhook-timestamp` | Unix seconds when the request was signed |
| `webhook-signature` | `v1,` plus base64 HMAC-SHA256 |
| `X-Shellui-Event` | Event type, for example `hosting.deployment.succeeded` |
| `X-Shellui-Delivery-Attempt` | Attempt number. `1` on the first try |
| `Authorization` | Optional. Copied from the rule |

The body is compact JSON with sorted keys, UTF-8, and non-ASCII characters left as characters. Verifiers must use the raw request body bytes.

Signed content is `{webhook-id}.{webhook-timestamp}.{raw body}`.

## Verify the signature in a Code node

Add a **Code** node directly after the Webhook node. Mode: **Run Once for All Items**. Language: **JavaScript**.

The node reads `SHELLUI_WEBHOOK_SECRET` from the n8n environment. It rejects a missing header, a timestamp older than 300s, and a signature that does not match. Configure the Webhook node to pass the raw body as binary when your n8n version can. Otherwise the Code node must see the same bytes Shellui signed.

```javascript
const crypto = require('crypto');

const MAX_AGE_SECONDS = 300;
const secret = $env.SHELLUI_WEBHOOK_SECRET;

function signingKey(secret) {
  if (secret.startsWith('whsec_')) {
    return Buffer.from(secret.slice('whsec_'.length), 'base64');
  }
  return Buffer.from(secret, 'utf8');
}

const item = $input.first();
const headers = item.json.headers || {};
const body = item.binary?.data
  ? Buffer.from(item.binary.data.data, 'base64')
  : Buffer.from(JSON.stringify(item.json.body ?? item.json), 'utf8');

const msgId = headers['webhook-id'] || headers['Webhook-Id'];
const msgTs = headers['webhook-timestamp'] || headers['Webhook-Timestamp'];
const msgSig = headers['webhook-signature'] || headers['Webhook-Signature'];

if (!msgId || !msgTs || !msgSig) {
  throw new Error('Missing Standard Webhooks headers');
}

const ts = parseInt(msgTs, 10);
const now = Math.floor(Date.now() / 1000);
if (Number.isNaN(ts) || Math.abs(now - ts) > MAX_AGE_SECONDS) {
  throw new Error('webhook-timestamp too old or invalid');
}

const signed = `${msgId}.${msgTs}.${body.toString('utf8')}`;
const key = signingKey(secret);
const digest = crypto.createHmac('sha256', key).update(signed, 'utf8').digest('base64');
const expected = `v1,${digest}`;
const provided = String(msgSig).split(' ')[0];
if (provided !== expected) {
  throw new Error('Invalid webhook signature');
}

return [{
  json: {
    verified: true,
    event: headers['x-shellui-event'],
    webhook_id: msgId,
  },
}];
```

Store `webhook_id` in workflow static data or another store so a retry does not run the rest of the workflow twice.

## Check a signature in Node.js

This function is the same check without n8n helpers. [verify-shellui-webhook.mjs](examples/verify-shellui-webhook.mjs) compares the digest in constant time. Prefer that file when you are not inside n8n.

```javascript
const crypto = require('crypto');

function verifyShelluiWebhook({
  secret,
  rawBody,
  webhookId,
  webhookTimestamp,
  webhookSignature,
  maxAgeSeconds = 300,
}) {
  const ts = parseInt(webhookTimestamp, 10);
  const now = Math.floor(Date.now() / 1000);
  if (Number.isNaN(ts) || Math.abs(now - ts) > maxAgeSeconds) {
    return false;
  }
  const key = secret.startsWith('whsec_')
    ? Buffer.from(secret.slice('whsec_'.length), 'base64')
    : Buffer.from(secret, 'utf8');
  const signed = `${webhookId}.${webhookTimestamp}.${rawBody.toString('utf8')}`;
  const digest = crypto.createHmac('sha256', key).update(signed, 'utf8').digest('base64');
  const expected = `v1,${digest}`;
  const provided = String(webhookSignature).split(' ')[0];
  return provided === expected;
}
```

## Retry behavior

| HTTP result | Outbox |
| --- | --- |
| 2xx | Delivered |
| 404, 408, 409, 425, 429, and other 4xx not listed below | Retry with backoff |
| 400, 401, 403, 405, 410, 413, 422 | Dead. Fix the rule or the workflow, then requeue |
| 5xx, timeouts, connection errors | Retry |
| 429 or 503 with `Retry-After` | Next attempt respects the header, max 1 hour |

Backoff is `30s * 2^(n-1)`, capped at 1 hour, up to 8 attempts. Cron is `python manage.py retry_webhooks` every minute. See [Maintenance jobs](maintenance-jobs.md).

## Self-hosted n8n on a private network

Shellui blocks private and localhost webhook URLs (SSRF protection). For n8n on a private address or a Docker DNS name:

- Staff can enable **allow private URLs** on that rule, or
- Set `ACTIONS_WEBHOOK_ALLOW_PRIVATE=true`

When the variable is unset, it follows `DEBUG`, so a local hosting-service already allows those URLs. Leave it off in production unless you accept the risk of the service calling internal addresses.

## Example envelopes

`hosting.app.created`:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "hosting.app.created",
  "time": "2026-09-24T13:30:00+00:00",
  "company": { "id": 1 },
  "data": {
    "app_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "my-app",
    "slug": "vpzzsxvzsmp7",
    "display_name": "My App",
    "company_id": 1
  }
}
```

`hosting.deployment.succeeded`:

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "type": "hosting.deployment.succeeded",
  "time": "2026-09-24T13:35:00+00:00",
  "company": { "id": 1 },
  "data": {
    "app_id": "550e8400-e29b-41d4-a716-446655440000",
    "deployment_id": "770e8400-e29b-41d4-a716-446655440002",
    "app_version": "1.0.0",
    "shellui_version": "0.5.0",
    "status": "active"
  }
}
```

The full catalog is in [Webhooks](actions.md).

## What to do in admin

1. **Send test event** on a rule while the n8n test URL is listening.
2. Open **Deliveries** for status, attempts, and errors.
3. **Requeue** a dead or failed row after n8n is fixed (workflow active, URL correct, auth aligned).

API paths and the retry command are in [Webhooks](actions.md).
