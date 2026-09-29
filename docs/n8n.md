# Using Shellui webhooks with n8n

Shellui hosting (and other Shellui services) can POST signed JSON to an **n8n Webhook** node when hosting events fire. This guide matches the behavior shared with identity-service and storage-service Shellui Actions.

---

## Quick checklist

1. Add a **Webhook** node (POST). Set **Respond** to **Immediately** so Shellui gets a fast 2xx before your workflow finishes.
2. Copy the **Production URL** (or **Test URL** while building). Activate the workflow for production URLs.
3. In Shellui admin, create a Shellui Action rule: event type, webhook URL, signing secret (`whsec_…` or plain text).
4. Optional: set **Authorization** on the rule (Header Auth or Basic Auth in n8n).
5. Verify signatures on the **raw body** (see Code node below). Dedupe on `webhook-id` (same id on retries).
6. Use **Send test event** in admin with n8n **Listen for test event** on the test URL.

Default HTTP timeout from Shellui is **5 seconds** (`ACTIONS_WEBHOOK_TIMEOUT_SECONDS`). Respond immediately in n8n to stay within that budget.

---

## Webhook node setup

| Setting | Value |
| -------- | ----- |
| HTTP Method | POST |
| Path | Default or custom |
| Respond | **Immediately** |
| Authentication | None at the node if you verify HMAC in a Code node; or use **Header Auth** / **Basic Auth** and paste the same value into the Shellui rule **Authorization** field |

**Production vs test URL:** n8n shows a test URL while the editor listens once. Shellui **Send test event** works with the test URL when listening. For live hosting events, activate the workflow and use the production URL.

**404 from n8n:** An inactive workflow or a test URL that is not listening often returns HTTP 404. Shellui treats 404 as **retryable** (same as an offline endpoint). Activate the workflow or fix the URL; use the delivery log and **Requeue** after n8n is ready.

---

## Signing secret format

Shellui accepts:

- **Standard Webhooks style:** `whsec_` plus base64-encoded random bytes (32 bytes recommended). Shellui decodes the suffix and uses those bytes as the HMAC key.
- **Plain text:** any string; UTF-8 bytes are the HMAC key.

Generate a compatible secret in Python:

```python
from apps.actions.webhook_signing import generate_webhook_signing_secret
print(generate_webhook_signing_secret())
```

Shellui auto-generates a `whsec_` secret when you create a rule without one. The **create** and **rotate-secret** API responses return the full `secret` once; later reads expose `has_secret` and `secret_hint` (last four characters) only.

Reference verifier script: [verify-shellui-webhook.mjs](examples/verify-shellui-webhook.mjs) (run with Node.js).

Store the same value in n8n (for manual verification) and in the Shellui Action rule.

---

## Request headers

| Header | Meaning |
| ------ | ------- |
| `Content-Type` | `application/json; charset=utf-8` |
| `webhook-id` | Same as envelope `id`; stable across retries |
| `webhook-timestamp` | Unix seconds when the request was signed |
| `webhook-signature` | `v1,<base64(hmac_sha256)>` |
| `X-Shellui-Event` | Event type, e.g. `hosting.deployment.succeeded` |
| `X-Shellui-Delivery-Attempt` | Attempt number (1 on first try) |
| `Authorization` | Optional; from rule config |

Body JSON is compact, sorted keys, **UTF-8 without ASCII escaping** (`ensure_ascii=false`). Verifiers must use the **raw request body bytes**, not a re-serialized JSON object.

Signed content: `{webhook-id}.{webhook-timestamp}.{raw_body_bytes}`.

---

## n8n Code node (verify signature)

Add a **Code** node right after the Webhook node. Mode: **Run Once for All Items**. Language: **JavaScript**.

```javascript
const crypto = require('crypto');

const MAX_AGE_SECONDS = 300;
const secret = $env.SHELLUI_WEBHOOK_SECRET; // set in n8n credentials / env

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
if (Number.isNaN(ts) || Math.abs(Math.floor(Date.now() / 1000) - ts) > MAX_AGE_SECONDS) {
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

// Dedupe: store msgId in workflow static data or an external store
return [{ json: { verified: true, event: headers['x-shellui-event'], webhook_id: msgId } }];
```

Configure the Webhook node to pass **Raw Body** into binary if your n8n version supports it; otherwise ensure the Code node reads the same bytes Shellui signed.

---

## Node.js verifier (plain crypto)

```javascript
const crypto = require('crypto');

function verifyShelluiWebhook({
  secret,
  rawBody, // Buffer
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
  let key;
  if (secret.startsWith('whsec_')) {
    key = Buffer.from(secret.slice('whsec_'.length), 'base64');
  } else {
    key = Buffer.from(secret, 'utf8');
  }
  const signed = `${webhookId}.${webhookTimestamp}.${rawBody.toString('utf8')}`;
  const digest = crypto.createHmac('sha256', key).update(signed, 'utf8').digest('base64');
  const expected = `v1,${digest}`;
  const provided = String(webhookSignature).split(' ')[0];
  return provided === expected;
}
```

---

## Retry behavior (Shellui side)

| HTTP result | Outbox retry |
| ----------- | ------------- |
| 2xx | Delivered |
| **404**, 408, 409, 425, 429, other 4xx not listed below | Retry with backoff |
| 400, 401, 403, 405, 410, 413, 422 | **Dead** (fix config, then requeue manually) |
| 5xx, timeouts, connection errors | Retry |
| 429 / 503 with `Retry-After` | Next attempt respects header (max 1 hour) |

Backoff default: `30s * 2^(n-1)` capped at 1 hour, up to 8 attempts. Cron: `python manage.py retry_webhooks` every minute.

---

## Self-hosted n8n on a private network

Shellui blocks private and localhost URLs by default (SSRF protection). For n8n on `http://10.x.x.x` or Docker internal DNS:

- Staff: enable **allow private URLs** on the rule, or
- Set `ACTIONS_WEBHOOK_ALLOW_PRIVATE=true` in hosting-service (development only unless you accept the risk).

---

## Example hosting envelopes

**`hosting.app.created`**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "hosting.app.created",
  "time": "2026-09-24T13:30:00+00:00",
  "company": { "id": 1 },
  "data": {
    "app_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "my-app",
    "slug": "abc12345",
    "display_name": "My App",
    "company_id": 1
  }
}
```

**`hosting.deployment.succeeded`**

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

Full catalog: [actions.md](actions.md).

---

## Admin workflow

1. **Send test event** on a rule while n8n test URL is listening.
2. Inspect **Deliveries** for status, attempts, and errors.
3. **Requeue** a dead or failed row after fixing n8n (activate workflow, correct URL, auth).

See also [actions.md](actions.md) for API paths and cron setup.
