"""MCP admin operation summaries and bodies. Consumed by ``openapi_admin.mcp_openapi_fields``."""

from __future__ import annotations

from typing import NamedTuple


class _McpSpec(NamedTuple):
    summary: str
    lead: str
    side_effects: str
    sends_email: bool = False
    destructive: bool = False
    notes: str = ''
    # One or two sentences for the MCP tool description (what it does, key arguments, return).
    agent: str = ''


# Keys must match ``MCP_REQUIRED_OPERATION_IDS`` in ``apps.authapi.mcp_openapi``.
MCP_SPECS: dict[str, _McpSpec] = {
    'hosting_v1_access_request_create': _McpSpec(
        'Request hosting access for your company',
        'Adds the company to the hosting waitlist with status `pending`. Staff approve or deny separately.',
        'Inserts or refreshes a hosting access row.',
        notes='Does not grant deploy rights until staff set status to `approved`.',
        agent=(
            'Adds your company to the Shellui hosting waitlist and returns the access row with status pending. '
            'Staff approve or deny it separately.'
        ),
    ),
    'hosting_v1_preview_create': _McpSpec(
        'Prepare a preview deploy',
        'Creates or refreshes a preview site under the caller company. Returns app metadata, a draft deployment, '
        'and public URLs. Preview sites expire 7 days after the last successful finalize or renew-expiry call '
        '(`HOSTING_PREVIEW_TTL_DAYS`, default 7). Production slugs do not use this TTL.',
        'Creates or updates app and deployment rows and may register OAuth redirect hints with identity-service.',
        agent=(
            'Creates or refreshes a preview site from app_version and shellui_version (optional slug) and returns '
            'the app, a draft deployment, and public URLs. Preview sites expire 7 days after the last successful '
            'finalize or renew-expiry call.'
        ),
    ),
    'hosting_v1_apps_list': _McpSpec(
        'List hosted sites for your company',
        'Returns every app (production and preview) for the JWT `company_id`, including `expires_at` on previews.',
        'Read-only.',
        agent=(
            'Lists every hosted site for your company and returns each app id, slug, display name, '
            'current deployment, and preview expiry when set.'
        ),
    ),
    'hosting_v1_apps_create': _McpSpec(
        'Register a hosted site slug',
        'Creates an app row with a unique slug under the company. Upload and finalize deployments separately.',
        'Inserts an app record and may register OAuth redirect metadata.',
        agent=(
            'Registers a hosted site from name (the slug) and optional display_name, and returns the new app. '
            'Upload and finalize a deployment in later calls.'
        ),
    ),
    'hosting_v1_apps_retrieve': _McpSpec(
        'Read one hosted site',
        'Looks up a site by slug or UUID within the company. Includes preview `expires_at` when set.',
        'Read-only.',
        agent='Reads the hosted site app_ref (slug or UUID) and returns its metadata, including preview expires_at when set.',
    ),
    'hosting_v1_apps_destroy': _McpSpec(
        'Delete a hosted site',
        'Removes the app, its deployments, and stored artifacts for the company.',
        'Deletes app, deployment, and storage objects.', destructive=True,
        notes='Irreversible. Active traffic stops after DNS and serve cache TTLs elapse.',
        agent=(
            'Deletes the hosted site app_ref, including deployments and stored artifacts, and returns an empty result. '
            'This cannot be undone.'
        ),
    ),
    'hosting_v1_apps_renew_expiry_create': _McpSpec(
        'Extend preview site expiry',
        'Resets preview `expires_at` to now plus **7 days** (`HOSTING_PREVIEW_TTL_DAYS`, default 7). '
        'Production sites ignore this route.',
        'Updates the app `expires_at` timestamp.',
        agent='Extends preview site app_ref by 7 days and returns the updated app. Production sites ignore this call.',
    ),
    'hosting_v1_apps_deployments_list': _McpSpec(
        'List deployments for a site',
        'Returns deployment history for one app, newest first, with status and artifact metadata.',
        'Read-only.',
        agent='Lists deployments for site app_ref, newest first, and returns each deployment status and artifact metadata.',
    ),
    'hosting_v1_apps_deployments_create': _McpSpec(
        'Create a draft deployment',
        'Opens a new deployment row. Request an artifact upload URL, PUT the `.tar.gz` bytes to that URL, '
        'confirm upload, then call finalize to go live.',
        'Inserts a deployment row in `draft` status.',
        agent=(
            'Opens a draft deployment for app_ref from app_version and shellui_version, and returns the draft '
            'deployment id used for upload and finalize.'
        ),
    ),
    'hosting_v1_apps_deployments_artifact_upload_url_create': _McpSpec(
        'Hosting: mint artifact upload URL',
        'Returns a time-limited PUT URL and headers so the agent uploads the `.tar.gz` outside the MCP JSON stream. '
        'On S3 backends the URL is presigned. On filesystem backends PUT to hosting-service with the same agent Bearer token.',
        'Does not store bytes yet; only describes where to upload.',
        notes='After PUT, call artifact upload complete (required for S3; idempotent when bytes already registered).',
        agent=(
            'Returns a time-limited PUT URL and headers so you can upload the .tar.gz for deployment_id on app_ref '
            'outside this tool. Optional expires_in is how many seconds the URL stays valid.'
        ),
    ),
    'hosting_v1_apps_deployments_artifact_upload_complete_create': _McpSpec(
        'Hosting: confirm artifact upload',
        'Verifies the artifact object exists in storage and records its size on the deployment. '
        'Call after a successful PUT to the upload URL from the mint step.',
        'Updates deployment `artifact_size` and status to `uploading`.',
        notes='Safe to call again when `artifact_size` is already set (for example after a direct hosting PUT).',
        agent=(
            'Confirms the artifact for deployment_id on app_ref is in storage, records its size, and returns the '
            'deployment with status uploading.'
        ),
    ),
    'hosting_v1_apps_deployments_finalize_create': _McpSpec(
        'Finalize and activate a deployment',
        'Extracts the uploaded artifact, validates paths, and marks the deployment `active`. '
        'Preview apps reset the **7-day** expiry timer on success.',
        'Updates deployment status, app `current_deployment`, storage layout, and serve cache.',
        destructive=True,
        agent=(
            'Activates deployment_id on app_ref so the site serves that artifact, and returns the deployment. '
            'Preview sites reset the 7-day expiry timer on success.'
        ),
    ),
    'hosting_v1_apps_deployments_rollback_create': _McpSpec(
        'Rollback to a previous deployment',
        'Reactivates an older successful deployment and supersedes the current active one.',
        'Updates active deployment pointers and clears serve cache.', destructive=True,
        notes='Does not delete artifact files; only changes which deployment is served.',
        agent=(
            'Serves the older deployment_id on app_ref again and returns that deployment as active. '
            'Artifact files stay in storage.'
        ),
    ),
    'hosting_v1_deploy_tokens_retrieve': _McpSpec(
        'List company deploy tokens',
        'Returns token metadata (prefix, expiry, last used). Plaintext secrets are never returned.',
        'Read-only.',
        agent=(
            'Lists deploy token metadata for your company and returns prefix, expiry, and last used time. '
            'Plaintext secrets are never included.'
        ),
    ),
    'hosting_v1_deploy_tokens_revoke_create': _McpSpec(
        'Revoke a deploy token',
        'Marks a deploy token revoked so it cannot upload or finalize preview deploys.',
        'Sets `revoked_at` on the token row.', destructive=True,
        agent=(
            'Revokes deploy token token_id so it cannot upload or finalize preview deploys, and returns the row '
            'with revoked_at set. This cannot be undone.'
        ),
    ),
    'hosting_v1_stats_retrieve': _McpSpec(
        'Read hosting usage stats',
        'Returns aggregate counts for apps and deployments in the company scope carried by the token.',
        'Read-only metrics.',
        agent='Returns aggregate app and deployment counts for your company.',
    ),
    'hosting_v1_apps_domains_list': _McpSpec(
        'List custom hostnames for a site',
        'Returns hostnames your company attached to the app. `verified` and `serving` stay false until the platform confirms DNS and edge routing.',
        'Read-only.',
        notes='Company scope is enforced from the JWT only.',
        agent=(
            'Lists custom hostnames on app_ref and returns hostname, DNS instructions, and status. '
            'verified and serving stay false until the platform confirms DNS.'
        ),
    ),
    'hosting_v1_apps_domains_create': _McpSpec(
        'Register a custom hostname',
        'Creates a row and returns DNS instructions plus a deterministic TXT token. '
        'Does not verify DNS and does not provision TLS in this release.',
        'Inserts `AppCustomDomain`. Emits `hosting.custom_domain.created`.',
        destructive=True,
        notes='Call `.../refresh` after DNS changes; status advances to `awaiting_platform` only. Never treat `verified` as true from this API.',
        agent=(
            'Registers hostname on app_ref and returns DNS TXT instructions plus a verification token. '
            'This does not verify DNS or issue TLS.'
        ),
    ),
    'hosting_v1_apps_domains_retrieve': _McpSpec(
        'Read one custom hostname',
        'Same fields as list, including `dns` and `instructions`.',
        'Read-only.',
        agent='Reads custom hostname domain_id on app_ref and returns hostname, DNS instructions, and status.',
    ),
    'hosting_v1_apps_domains_destroy': _McpSpec(
        'Remove a custom hostname',
        'Deletes the custom hostname row for the app.',
        'Deletes `AppCustomDomain`. Emits `hosting.custom_domain.deleted`.', destructive=True,
        agent='Removes custom hostname domain_id from app_ref and returns an empty result. This cannot be undone.',
    ),
    'hosting_v1_apps_domains_refresh_create': _McpSpec(
        'Refresh custom domain status',
        'Moves `pending_dns` to `awaiting_platform` when platform edge integration is still pending. '
        'Does not flip `verified` or `serving` without a real backend check.',
        'Updates `AppCustomDomain.status`. Emits `hosting.custom_domain.updated`.',
        destructive=True,
        agent=(
            'Refreshes custom hostname domain_id on app_ref, moves pending_dns to awaiting_platform, and returns '
            'the updated hostname. verified and serving stay false.'
        ),
    ),
    'hosting_v1_apps_environment_list': _McpSpec(
        'List app environment variables (names only)',
        'Returns keys and `value_present`. Values are never returned in list, get, or logs.',
        'Read-only.',
        notes='Tagged sensitive because key names can be secret-bearing.',
        agent=(
            'Lists environment variable names on app_ref and returns key, value_present, and updated_at. '
            'Values are never included.'
        ),
    ),
    'hosting_v1_apps_environment_create': _McpSpec(
        'Create or replace an environment variable',
        'Body: `key` and `value`. The value is encrypted at rest and is never echoed back.',
        'Upserts `AppEnvironmentVariable`. Emits `hosting.environment_variable.created` or `.updated`.',
        destructive=True,
        notes='Use PUT on `.../environment/{key}` to update by path.',
        agent=(
            'Creates or replaces an environment variable on app_ref from key and value, and returns key plus '
            'value_present. The value is encrypted and is not echoed.'
        ),
    ),
    'hosting_v1_apps_environment_retrieve': _McpSpec(
        'Read one environment variable (metadata only)',
        'Returns `key`, `value_present`, and `updated_at` only.',
        'Read-only.',
        agent=(
            'Reads environment variable key on app_ref and returns key, value_present, and updated_at. '
            'The stored value is not included.'
        ),
    ),
    'hosting_v1_apps_environment_update': _McpSpec(
        'Update an environment variable value',
        'Body: `value` only. Same encryption rules as create.',
        'Updates ciphertext. Emits `hosting.environment_variable.updated`.',
        destructive=True,
        agent=(
            'Replaces the value of environment variable key on app_ref and returns key plus value_present. '
            'The previous value cannot be read back.'
        ),
    ),
    'hosting_v1_apps_environment_destroy': _McpSpec(
        'Delete an environment variable',
        'Removes the stored key and ciphertext.',
        'Deletes row. Emits `hosting.environment_variable.deleted`.', destructive=True,
        agent='Deletes environment variable key from app_ref and returns an empty result. This cannot be undone.',
    ),
    'hosting_v1_apps_runtime_logs_list': _McpSpec(
        'Read runtime logs (availability contract)',
        'Static hosting does not collect process stdout. Response explains `unavailable_reason` with an empty `lines` list.',
        'Read-only.',
        agent=(
            'Reads runtime logs for app_ref (optional limit) and returns source none, an unavailable_reason, and an '
            'empty lines list because static hosting has no process output.'
        ),
    ),
    'hosting_v1_apps_request_logs_list': _McpSpec(
        'List recent HTTP requests for the site',
        'Returns anonymized rows from app-host traffic (method, path, status, optional request id). '
        '`cursor` pages backward by id; `limit` is capped server-side.',
        'Read-only.',
        notes='Recorded only for traffic on `{slug}.{HOSTING_APP_DOMAIN}` style hosts when `HOSTING_REQUEST_LOG_ENABLED` is true.',
        agent=(
            'Lists recent HTTP requests for app_ref and returns status code, request path, and HTTP method for each row. '
            'Optional limit, cursor, status_min, and status_max page and filter the list.'
        ),
    ),
    'api_v1_actions_events_list': _McpSpec(
        'List Shellui Actions event types',
        'Returns domain event ids, labels, and payload field docs you can subscribe to with webhook rules.',
        'Read-only.',
        agent='Lists Shellui Actions event types you can subscribe to and returns each event id, label, and payload field docs.',
    ),
    'api_v1_actions_rules_list': _McpSpec(
        'List Shellui Actions webhook rules',
        'Each rule posts signed HTTPS webhooks when a hosting domain event fires. '
        'Secrets are write-only except immediately after create or rotate.',
        'Read-only.',
        agent='Lists Shellui Actions webhook rules for your company and returns rule metadata. Signing secrets are omitted.',
    ),
    'api_v1_actions_rules_create': _McpSpec(
        'Create a Shellui Actions webhook rule',
        'Creates an HTTPS webhook rule for a registered `event_type`. '
        'Returns the signing `secret` once in the response body.',
        'Inserts rule row and stores encrypted secret.',
        notes='Store `secret` before closing the response. URL must be publicly reachable unless staff SSRF override is enabled.',
        agent=(
            'Creates a Shellui Actions webhook rule from name, event_type, and url, and returns the rule metadata. '
            'The plaintext signing secret is omitted.'
        ),
    ),
    'api_v1_actions_rules_retrieve': _McpSpec(
        'Read one Shellui Actions webhook rule',
        'Returns rule metadata and masked secret hints. Plaintext `secret` is omitted.',
        'Read-only.',
        agent=(
            'Reads Shellui Actions webhook rule id and returns its metadata with a masked secret hint. '
            'The plaintext secret is omitted.'
        ),
    ),
    'api_v1_actions_rules_partial_update': _McpSpec(
        'Update a Shellui Actions webhook rule',
        'Patches name, description, enabled flag, URL, or authorization header.',
        'Updates rule configuration.',
        agent='Updates Shellui Actions webhook rule id (name, description, enabled, url, or authorization header) and returns the rule.',
    ),
    'api_v1_actions_rules_destroy': _McpSpec(
        'Delete a Shellui Actions webhook rule',
        'Removes the rule. In-flight deliveries may still complete.',
        'Deletes the rule row.', destructive=True,
        agent='Deletes Shellui Actions webhook rule id and returns an empty result. In-flight deliveries may still finish.',
    ),
    'api_v1_actions_rules_rotate_secret': _McpSpec(
        'Rotate a webhook signing secret',
        'Generates a new HMAC secret and returns it once in the response body.',
        'Updates encrypted secret on the rule.',
        destructive=True,
        notes='Update your receiver before relying on the new secret.',
        agent=(
            'Rotates the signing secret for Shellui Actions webhook rule id and returns the rule with the secret masked. '
            'Update your receiver before you rely on the new secret.'
        ),
    ),
    'api_v1_actions_rules_send_test': _McpSpec(
        'Queue a sample webhook delivery',
        'Sends a synthetic domain event payload to the rule URL for connectivity testing.',
        'Records a delivery attempt.', sends_email=False, destructive=True,
        notes='Does not send email. Delivers an HTTPS webhook only.',
        agent='Sends a sample webhook to the URL on Shellui Actions rule id and returns whether that delivery succeeded. This does not send email.',
    ),
    'api_v1_actions_deliveries_list': _McpSpec(
        'List recent webhook deliveries',
        'Returns delivery status, attempt counts, and errors for the company.',
        'Read-only.',
        notes='Staff may filter by `scheduled_job_run_id` (not exposed on MCP).',
        agent=(
            'Lists recent Shellui Actions webhook deliveries and returns status, attempt counts, and errors. '
            'Optional status filters to pending, delivered, failed, or dead.'
        ),
    ),
    'api_v1_actions_deliveries_retrieve': _McpSpec(
        'Read one webhook delivery',
        'Returns attempts, HTTP statuses, and the signed envelope payload.',
        'Read-only.',
        agent='Reads Shellui Actions webhook delivery delivery_id and returns attempts, HTTP statuses, and the signed envelope.',
    ),
    'api_v1_actions_deliveries_requeue': _McpSpec(
        'Requeue a failed webhook delivery',
        'Resets a failed or dead delivery to pending for another attempt.',
        'Updates outbox status and schedule.',
        destructive=True,
        agent='Requeues a failed or dead Shellui Actions delivery delivery_id and returns it with status pending.',
    ),
    'api_v1_actions_event_log_list': _McpSpec(
        'List recent domain events for the company',
        'Returns hosting domain events stored for auditing and Shellui Actions rules.',
        'Read-only.',
        agent=(
            'Lists recent domain events for your company and returns the matching rows. '
            'Optional event_type filters to one catalog event id.'
        ),
    ),
    'api_v1_actions_event_log_retrieve': _McpSpec(
        'Read one domain event log entry',
        'Returns full event payload for one company row.',
        'Read-only.',
        agent='Reads domain event log row id and returns the full event payload for that row.',
    ),
    'api_v1_actions_event_log_types_list': _McpSpec(
        'List domain event type ids',
        'Returns event type strings valid for log filters and Shellui Actions rules.',
        'Read-only.',
        agent=(
            'Lists domain event type ids you can use in event log filters and Shellui Actions rules, and returns '
            'each type, label, and description.'
        ),
    ),
    'api_v1_actions_event_log_retention_retrieve': _McpSpec(
        'Read event log retention settings',
        'Returns configured retention days and whether stale events suggest the purge job is behind.',
        'Read-only.',
        agent=(
            'Returns how many days Shellui keeps company domain events, the oldest event time, and whether '
            'older rows suggest the purge job is behind.'
        ),
    ),
}


_MISSING_AGENT = [key for key, spec in MCP_SPECS.items() if not spec.agent.strip()]
if _MISSING_AGENT:
    raise AssertionError(f'MCP agent descriptions missing: {_MISSING_AGENT}')
