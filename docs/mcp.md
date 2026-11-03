---
title: Shellui MCP
description: Company-owner hosting APIs exposed to Shellui MCP agents through OpenAPI markers and the hosting /mcp endpoint.
---

# Shellui MCP

Shellui MCP connects AI agents to company-owner hosting APIs. Identity-service issues OAuth agent tokens; hosting-service exposes `POST /mcp` and publishes OpenAPI `x-mcp` markers so only opted-in routes become tools.

## How tools are chosen

An HTTP operation becomes an MCP tool only when its OpenAPI entry includes an explicit `mcp_tool(...)` decoration (surfaced as `x-mcp` in the schema). Internal routes, scheduled jobs, staff-only access approval, metrics, and binary artifact upload are excluded.

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
| Deployments | `deployments` | List, create, finalize, rollback |
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

## Access modes

Agent JWT claims mirror Identity: `mcp_access` (`read_only`, `ask`, `full`), `mcp_read` (`safe`, `sensitive`), and `mcp_destructive`. Read-only agents cannot call write routes. Ask mode creates an approval request in Identity before mutating data.
