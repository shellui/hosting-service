---
title: Shellui MCP
description: Company-owner hosting APIs exposed to Shellui MCP agents through OpenAPI markers and the hosting /mcp endpoint.
---

# Shellui MCP

Shellui MCP connects AI agents to company-owner hosting APIs. Identity-service issues OAuth agent tokens; hosting-service exposes `POST /mcp` and publishes OpenAPI `x-mcp` markers so only opted-in routes become tools.

## How tools are chosen

An HTTP operation becomes an MCP tool only when its OpenAPI entry includes an explicit `mcp_tool(...)` decoration (surfaced as `x-mcp` in the schema). Internal routes, scheduled jobs, staff-only access approval, metrics, and the raw binary `PUT .../upload` route are excluded. Agents upload artifacts with JSON MCP tools that mint a PUT URL, then send bytes directly over HTTPS.

Operations carry:

```yaml
x-mcp:
  read_only: true|false
  destructive: true|false
  sensitive: true|false
```

Response fields may use `x-mcp-secret` (never return plaintext to agents) or `x-mcp-sensitive` (mask in read-safe modes).

## Agent-visible hosting APIs

| Area | OpenAPI tag | Examples |
| --- | --- | --- |
| Sites | `sites` | List, create, read, delete apps |
| Deployments | `deployments` | List, create, artifact upload URL, upload complete, finalize, rollback |
| Previews | `previews` | Prepare preview deploy, renew 7-day expiry |
| Deploy tokens | `deploy-tokens` | List metadata and revoke (create stays admin or user JWT only) |
| Webhooks | `webhooks` | Shellui Actions rules and deliveries |
| Event log | `event-log` | Company domain events |

Preview sites use a **7-day TTL** (`HOSTING_PREVIEW_TTL_DAYS`). Production sites do not expire through this API.

Deploy tokens are stored hashed. List and read responses never include plaintext tokens. Create returns `token` once for company-owner user JWTs and admin only; Shellui MCP agents cannot create deploy tokens or read plaintext values.

## MCP endpoint

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/mcp` | JSON-RPC (`initialize`, `tools/list`, `tools/call`) |
| `GET` | `/.well-known/oauth-protected-resource` | Points agents at Identity for OAuth |

Use a Bearer agent access token from Identity with the `hosting` service scope and an `aud` claim that exactly matches this service's MCP resource URL (RFC 8707, `{origin}/mcp`). Revocation is enforced via Identity `GET /api/v1/mcp/internal/mcp-revocations` with a signed service assertion (cached 30 seconds on hosting). If that poll fails, MCP requests are denied until Identity responds again. When Identity signs the revocation list payload, hosting verifies the response assertion before trusting agent ids.

After a company owner approves a pending write in Identity, the agent retries the same tool call; hosting checks approval state with Identity and runs the write once.

## Deploy a site end to end

Use a company-owner agent token with the `hosting` scope and write access (`mcp_access` `full` or approved `ask` writes). Each step is an MCP `tools/call` except the byte upload, which uses HTTPS PUT outside JSON-RPC.

1. **Register or pick a site** - `hosting_v1_apps_create` or `hosting_v1_preview_create` (preview) or `hosting_v1_apps_list` / `hosting_v1_apps_retrieve`.
2. **Open a draft deployment** - `hosting_v1_apps_deployments_create` with `app_version` and `shellui_version`.
3. **Mint an upload URL** - `hosting_v1_apps_deployments_artifact_upload_url_create`. The response includes `upload_url`, `method` (`PUT`), `headers`, and `requires_bearer`.
4. **Upload the archive** - HTTP `PUT` the `.tar.gz` to `upload_url` with the given headers. When `requires_bearer` is true, send the same `Authorization: Bearer` agent token on the PUT. Do not send the tarball through MCP.
5. **Confirm upload** - `hosting_v1_apps_deployments_artifact_upload_complete_create`. Required after S3 presigned PUT; idempotent when the direct hosting PUT already registered size.
6. **Go live** - `hosting_v1_apps_deployments_finalize_create`.

The legacy `PUT /hosting/v1/apps/{app_ref}/deployments/{id}/upload` route remains for the CLI and deploy tokens. It is not an MCP tool because MCP carries JSON only.

## Access modes

Agent JWT claims mirror Identity: `mcp_access` (`read_only`, `ask`, `full`), `mcp_read` (`safe`, `sensitive`), and `mcp_destructive`. Read-only agents cannot call write routes. Ask mode creates an approval request in Identity before mutating data.

## Internal assertions to Identity

Revocation polling, approvals and call logs send Identity a short-lived RS256 assertion signed with this service's own key (`HOSTING_SERVICE_SIGNING_KEY`, issuer `HOSTING_SERVICE_ISSUER`, `shellui-django` 0.4.0+). The public key is served at `GET /.well-known/jwks.json`. Identity trusts it only when its own `HOSTING_SERVICE_ISSUER` matches, and reads the key from `HOSTING_SERVICE_JWKS_URL` or a pinned `HOSTING_SERVICE_JWKS`. Without a key, MCP fails closed: agents are refused and call logs are skipped.

Generate a key with `openssl genrsa 3072` and keep it in a secret store or a mounted file (`HOSTING_SERVICE_SIGNING_KEY_FILE`).
