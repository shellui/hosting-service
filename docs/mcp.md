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
| Operations | `operations` | Custom domains, app environment keys, request logs, runtime log contract |
| Deploy tokens | `deploy-tokens` | List metadata and revoke (create stays admin or user JWT only) |
| Webhooks | `webhooks` | Shellui Actions rules and deliveries |
| Event log | `event-log` | Company domain events |

Preview sites use a **7-day TTL** (`HOSTING_PREVIEW_TTL_DAYS`). Production sites do not expire through this API.

Deploy tokens are stored hashed. List and read responses never include plaintext tokens. Create returns `token` once for company-owner user JWTs and admin only; Shellui MCP agents cannot create deploy tokens or read plaintext values.

## Operations after deploy

Company scope always comes from the JWT `company_id`, never from a query parameter.

### Custom domains

- `GET/POST /hosting/v1/apps/{app_ref}/domains`, `GET/DELETE .../domains/{domain_id}`, `POST .../domains/{domain_id}/refresh`
- Responses include DNS TXT instructions and keep `verified` and `serving` false until a future platform integration confirms provisioning. `refresh` only moves local status from `pending_dns` to `awaiting_platform` so agents never see a fake green check.

### Environment variables

- `GET/POST /hosting/v1/apps/{app_ref}/environment`, `GET/PUT/DELETE .../environment/{key}`
- List and read return `key`, `value_present`, and `updated_at` only. Write bodies mark `value` with `x-mcp-secret`. Values are encrypted at rest and must never be logged by agents.

### Logs

- `GET /hosting/v1/apps/{app_ref}/logs/runtime` returns `source: none` and an explicit `unavailable_reason` because static hosting has no process logs in this release.
- `GET /hosting/v1/apps/{app_ref}/logs/requests` pages backward with `cursor` and `limit` (server-capped). Rows come from app-subdomain traffic when `HOSTING_REQUEST_LOG_ENABLED` is true. They include method, path, and status only.

## MCP endpoint

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/mcp` | JSON-RPC (`initialize`, `tools/list`, `tools/call`) |
| `GET` | `/.well-known/oauth-protected-resource` | Points agents at Identity for OAuth |

Use a Bearer agent access token from Identity with the `hosting` service scope and an `aud` claim that exactly matches this service's MCP resource URL (RFC 8707, `{origin}/mcp`). Revocation is enforced via Identity `GET /api/v1/mcp/internal/mcp-revocations` with a signed service assertion (cached 30 seconds on hosting). If that poll fails, MCP requests are denied until Identity responds again. When Identity signs the revocation list payload, hosting verifies the response assertion before trusting agent ids. The list's `agents` entries describe revoked or excluded snapshots; **not** being listed does **not** prove an active delegated agent. For regional tokens with `mcp_authority` = `delegated` and SaaS binding claims, hosting also calls Identity **`POST /api/v1/mcp/internal/mcp-agent-delegated-authority`** with a **hosting** service-signed bearer assertion: `aud` = `shellui-mcp-agent-delegated-authority`, `scope` = `mcp.agent.delegated.authority.read`, `target` = Identity issuer (`JWT_ISSUER`). The JSON body matches the token: `agent_id` (uuid), regional `company_id` (positive int), `global_company_id` (uuid), `grant_version`, `company_binding_version` (strict JSON ints; `0` valid). **200** must be **only** these keys (no `active`, `id`, or aliases), as returned by [``McpInternalDelegatedAgentAuthorityView`` at d79d433278ac18695a6165448bf0b8cfe56c88a5](https://github.com/shellui/identity-service/blob/d79d433278ac18695a6165448bf0b8cfe56c88a5/apps/agents/internal_views.py): `authorized`, `revoked`, `paused` (bools); regional `agent_id`; `global_agent_id`; regional `company_id` (int); `global_company_id`; `grant_version`; `company_binding_version`. Identity loads the ``Agent`` by uuid **and** regional ``company_id``, checks SaaS binding, grant, and ``GlobalAgentRevocation``, then returns that snapshot (no service or capability echo on 200). Hosting still requires `authorized` true, `revoked` false, `paused` false, exact echo of ids and versions with **native ints**, and ``hosting`` in the JWT ``scope`` so the token cannot omit hosting at the edge. Any mismatch or extra field denies. **403** with `authorized` false is an ordinary deny (stale binding, inactive, global revocation, or mismatch). **400** is malformed body; **404** is missing agent or not a delegated exchange agent. Hosting treats assertion build failure or Identity **5xx** / network errors as **503** on `POST /mcp` (no substitute for the live row on genuine denies; revocation polling is unchanged). **404** on this route when Identity is older than the canonical path is a configuration mismatch: set `IDENTITY_DELEGATED_AGENT_AUTHORITY_PATH` to the path your Identity build serves, or upgrade Identity. Retire alternate paths such as `mcp-delegated-agent-authority`; only `mcp-agent-delegated-authority` is canonical. Hosting caches a positive authority check for at most five seconds; untrusted revocation polls bump the cache generation so stale allow results are not reused. A revoked id applies only when there is exactly one unambiguous `agents` row that matches this request's agent, regional `company_id`, authority snapshot (`grant_version`, `company_binding_version` when present), and global company UUID when the token carries delegated proof. Absent or conflicting rows fail closed (deny).

**CLI vs AI gateway:** Personal regional tokens use `resource={hosting_origin}/mcp` at `POST /oauth/mcp/token` on Identity. The **per-company AI gateway** uses `{AI_SERVICE_URL}/c/<company_id>/mcp` as `resource` for the same token endpoint; downstream tools still call hosting with `Bearer` tokens whose `aud` is that resource URL, while tool names stay the registered OpenAPI **`operationId`** values (for example `hosting_v1_apps_list`, not a URL path). `tools/list` is driven by `x-mcp` markers (`tools/list` lists every opted-in `operationId`).

Tool **`arguments.path`** values use **hyphenated** OpenAPI path templates (for example `/hosting/v1/apps/{app_ref}/deployments/{id}`); that is the registry string passed to `resolve()`, not an underscored alias.

After a company owner approves a pending write in Identity, the agent retries the same tool call; hosting checks approval state with Identity and runs the write once. If Identity reports the approval as already consumed (`executed`), hosting records **`failed`** with fixed **`approval_expired`** (not `session_used`). **`session_used`** is reserved for a distinct reuse case outside this flow.

A successful consume step is not inferred from HTTP status alone. Identity must return JSON with `"consumed": true` (boolean). Any other 2xx body counts as a failed consume, so the write does not run.

**Personal regional agents** (direct `aud` for this service): signed approvals use the regional numeric `company_id`, `agent_id`, `service`, `action`, `arguments_hash`, and `target` (identity origin). When Identity issues `grant_version` on the agent JWT, hosting passes the same non-negative integer into create, state, and consume assertions (`0` is valid). When the claim is absent, the assertion omits `grant_version` (legacy personal tokens).

**Profiles:** Identity marks agent access tokens with `mcp_authority`. The SaaS **global** profile (`mcp_authority` = `global_delegated`) must not call hosting MCP directly. A **regional exchanged** token (`mcp_authority` = `delegated`) carries canonical `global_company_id`, `global_agent_id` (SaaS agent uuid), non-negative `grant_version` (`0` is valid), and non-negative `company_binding_version`, with `aud` still the downstream MCP resource URL (hosting `{origin}/mcp` or the per-company AI gateway URL). Personal regional agents omit the global binding; optional `grant_version` only stays legacy-safe. A raw `global_company_id` without the delegated profile and full binding is rejected (`mcp_authority_delegated_on_direct_resource`).

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

The shared `shellui-django` write gate treats **every destructive operation as approval-gated**, even when `mcp_access` is `full`. The `mcp_destructive` claim does not skip approval for destructive tools. Non-destructive writes in `full` mode run without a pending approval.

## Internal assertions to Identity

Revocation polling, approvals and call logs send Identity a short-lived RS256 assertion signed with this service's own key (`HOSTING_SERVICE_SIGNING_KEY`, issuer `HOSTING_SERVICE_ISSUER`). Hosting pins `shellui-django` to the matching django-commons source revision (see `pyproject.toml`, merge `1f0754b421688ed26b7eb2e76b25b6fa3eea2a37`). Ordinary internal assertions use a **60** second lifetime (the library `INTERNAL_ASSERTION_MAX_LIFETIME_SECONDS` cap). First company provisioning or setup flows that Identity documents as longer-lived may use a bounded **600 to 900** second TTL only where Identity accepts that profile; routine tool traffic keeps the 60 second cap. The public key is served at `GET /.well-known/jwks.json`. Identity trusts it only when its own `HOSTING_SERVICE_ISSUER` matches, and reads the key from `HOSTING_SERVICE_JWKS_URL` or a pinned `HOSTING_SERVICE_JWKS`. Without a key, MCP fails closed: agents are refused and call logs are skipped. Hosting always calls Identity's live HTTP APIs for approvals and revocation; behavior is defined by those contracts and deployed services, not by a fixed documentation snapshot.

### Tool dispatch and call activity (`mcp-call-logs`)

Each MCP tool maps to one OpenAPI operation (`operationId` becomes the tool name). Django `resolve()` still runs on the materialized path for dispatch; **call logs** send the OpenAPI path template as `path` and the HTTP verb as `method` (no query string or raw user path). Identity derives labels server-side; hosting does **not** forward `operation_title`, `resource_label`, `arguments`, `arguments_redacted`, or arbitrary metadata (see [identity-service ``McpInternalCallLogView`` at d79d433278ac18695a6165448bf0b8cfe56c88a5](https://github.com/shellui/identity-service/blob/d79d433278ac18695a6165448bf0b8cfe56c88a5/apps/agents/internal_views.py)). Only explicit HTTP **2xx** map to `allowed` with **no** `error_code`. Every other outcome (`pending_approval`, `denied`, `failed`, `session_used`) carries a fixed `error_code` from the static enum (for example `service_unavailable`, `forbidden`, `approval_pending`, `approval_expired`). `POST /api/v1/mcp/internal/mcp-approval-requests` sends an **empty** JSON body; the signed assertion already binds `arguments_hash`, `agent_id`, strict `company_id`, and authority context. Forwarded fields include `agent_id`, `company_id`, `service`, `tool`, `path`, `method`, `status` (HTTP status int), `access_kind`, `outcome`, `duration_ms`, optional `error_code`, actor-derived `grant_version` / `company_binding_version` / `global_company_id`, and `approval_id` (UUID) when hosting minted an approval. Support outputs in OpenAPI do **not** imply Identity retains tool argument values; only hashes and server-derived labels apply.

Logs about failed Identity HTTP calls use fixed reason codes (`identity_request_failed`, `mcp_assertion_rule`, `mcp_assertion_error`, `audit_fields_incomplete`), not raw upstream response bodies.

### Globally delegated agents and the AI gateway

Direct hosting agent tokens must use an `aud` value that matches this service `{origin}/mcp` only. The SaaS `global_delegated` profile is refused at decode. Regional `delegated` tokens include the triplet in signed service assertions to Identity (matching `build_mcp_approval_assertion` in shellui-django). Gateway-only global flows still rely on exchange plus service-signed proof, not on forging headers at the hosting edge.

Generate a key with `openssl genrsa 3072` and keep it in a secret store or a mounted file (`HOSTING_SERVICE_SIGNING_KEY_FILE`).
