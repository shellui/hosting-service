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


# Keys must match ``MCP_REQUIRED_OPERATION_IDS`` in ``apps.authapi.mcp_openapi``.
MCP_SPECS: dict[str, _McpSpec] = {
    'hosting_v1_access_request_create': _McpSpec(
        'Request hosting access for your company',
        'Adds the company to the hosting waitlist with status `pending`. Staff approve or deny separately.',
        'Inserts or refreshes a hosting access row.',
        notes='Does not grant deploy rights until staff set status to `approved`.',
    ),
    'hosting_v1_preview_create': _McpSpec(
        'Prepare a preview deploy',
        'Creates or refreshes a preview site under the caller company. Returns app metadata, a draft deployment, '
        'and public URLs. Preview sites expire 7 days after the last successful finalize or renew-expiry call '
        '(`HOSTING_PREVIEW_TTL_DAYS`, default 7). Production slugs do not use this TTL.',
        'Creates or updates app and deployment rows and may register OAuth redirect hints with identity-service.',
    ),
    'hosting_v1_apps_list': _McpSpec(
        'List hosted sites for your company',
        'Returns every app (production and preview) for the JWT `company_id`, including `expires_at` on previews.',
        'Read-only.',
    ),
    'hosting_v1_apps_create': _McpSpec(
        'Register a hosted site slug',
        'Creates an app row with a unique slug under the company. Upload and finalize deployments separately.',
        'Inserts an app record and may register OAuth redirect metadata.',
    ),
    'hosting_v1_apps_retrieve': _McpSpec(
        'Read one hosted site',
        'Looks up a site by slug or UUID within the company. Includes preview `expires_at` when set.',
        'Read-only.',
    ),
    'hosting_v1_apps_destroy': _McpSpec(
        'Delete a hosted site',
        'Removes the app, its deployments, and stored artifacts for the company.',
        'Deletes app, deployment, and storage objects.', destructive=True,
        notes='Irreversible. Active traffic stops after DNS and serve cache TTLs elapse.',
    ),
    'hosting_v1_apps_renew_expiry_create': _McpSpec(
        'Extend preview site expiry',
        'Resets preview `expires_at` to now plus **7 days** (`HOSTING_PREVIEW_TTL_DAYS`, default 7). '
        'Production sites ignore this route.',
        'Updates the app `expires_at` timestamp.',
    ),
    'hosting_v1_apps_deployments_list': _McpSpec(
        'List deployments for a site',
        'Returns deployment history for one app, newest first, with status and artifact metadata.',
        'Read-only.',
    ),
    'hosting_v1_apps_deployments_create': _McpSpec(
        'Create a draft deployment',
        'Opens a new deployment row. Upload a `.tar.gz` artifact, then call finalize to go live.',
        'Inserts a deployment row in `draft` status.',
    ),
    'hosting_v1_apps_deployments_finalize_create': _McpSpec(
        'Finalize and activate a deployment',
        'Extracts the uploaded artifact, validates paths, and marks the deployment `active`. '
        'Preview apps reset the **7-day** expiry timer on success.',
        'Updates deployment status, app `current_deployment`, storage layout, and serve cache.',
    ),
    'hosting_v1_apps_deployments_rollback_create': _McpSpec(
        'Rollback to a previous deployment',
        'Reactivates an older successful deployment and supersedes the current active one.',
        'Updates active deployment pointers and clears serve cache.', destructive=True,
        notes='Does not delete artifact files; only changes which deployment is served.',
    ),
    'hosting_v1_deploy_tokens_retrieve': _McpSpec(
        'List company deploy tokens',
        'Returns token metadata (prefix, expiry, last used). Plaintext secrets are never returned.',
        'Read-only.',
    ),
    'hosting_v1_deploy_tokens_revoke_create': _McpSpec(
        'Revoke a deploy token',
        'Marks a deploy token revoked so it cannot upload or finalize preview deploys.',
        'Sets `revoked_at` on the token row.', destructive=True,
    ),
    'hosting_v1_stats_retrieve': _McpSpec(
        'Read hosting usage stats',
        'Returns aggregate counts for apps and deployments in the company scope carried by the token.',
        'Read-only metrics.',
    ),
    'api_v1_actions_events_list': _McpSpec(
        'List Shellui Actions event types',
        'Returns domain event ids, labels, and payload field docs you can subscribe to with webhook rules.',
        'Read-only.',
    ),
    'api_v1_actions_rules_list': _McpSpec(
        'List Shellui Actions webhook rules',
        'Each rule posts signed HTTPS webhooks when a hosting domain event fires. '
        'Secrets are write-only except immediately after create or rotate.',
        'Read-only.',
    ),
    'api_v1_actions_rules_create': _McpSpec(
        'Create a Shellui Actions webhook rule',
        'Creates an HTTPS webhook rule for a registered `event_type`. '
        'Returns the signing `secret` once in the response body.',
        'Inserts rule row and stores encrypted secret.',
        notes='Store `secret` before closing the response. URL must be publicly reachable unless staff SSRF override is enabled.',
    ),
    'api_v1_actions_rules_retrieve': _McpSpec(
        'Read one Shellui Actions webhook rule',
        'Returns rule metadata and masked secret hints. Plaintext `secret` is omitted.',
        'Read-only.',
    ),
    'api_v1_actions_rules_partial_update': _McpSpec(
        'Update a Shellui Actions webhook rule',
        'Patches name, description, enabled flag, URL, or authorization header.',
        'Updates rule configuration.',
    ),
    'api_v1_actions_rules_destroy': _McpSpec(
        'Delete a Shellui Actions webhook rule',
        'Removes the rule. In-flight deliveries may still complete.',
        'Deletes the rule row.', destructive=True,
    ),
    'api_v1_actions_rules_rotate_secret': _McpSpec(
        'Rotate a webhook signing secret',
        'Generates a new HMAC secret and returns it once in the response body.',
        'Updates encrypted secret on the rule.',
        notes='Update your receiver before relying on the new secret.',
    ),
    'api_v1_actions_rules_send_test': _McpSpec(
        'Queue a sample webhook delivery',
        'Sends a synthetic domain event payload to the rule URL for connectivity testing.',
        'Records a delivery attempt.', sends_email=False,
        notes='Does not send email. Delivers an HTTPS webhook only.',
    ),
    'api_v1_actions_deliveries_list': _McpSpec(
        'List recent webhook deliveries',
        'Returns delivery status, attempt counts, and errors for the company.',
        'Read-only.',
        notes='Staff may filter by `scheduled_job_run_id` (not exposed on MCP).',
    ),
    'api_v1_actions_deliveries_retrieve': _McpSpec(
        'Read one webhook delivery',
        'Returns attempts, HTTP statuses, and the signed envelope payload.',
        'Read-only.',
    ),
    'api_v1_actions_deliveries_requeue': _McpSpec(
        'Requeue a failed webhook delivery',
        'Resets a failed or dead delivery to pending for another attempt.',
        'Updates outbox status and schedule.',
    ),
    'api_v1_actions_event_log_list': _McpSpec(
        'List recent domain events for the company',
        'Returns hosting domain events stored for auditing and Shellui Actions rules.',
        'Read-only.',
    ),
    'api_v1_actions_event_log_retrieve': _McpSpec(
        'Read one domain event log entry',
        'Returns full event payload for one company row.',
        'Read-only.',
    ),
    'api_v1_actions_event_log_types_list': _McpSpec(
        'List domain event type ids',
        'Returns event type strings valid for log filters and Shellui Actions rules.',
        'Read-only.',
    ),
    'api_v1_actions_event_log_retention_retrieve': _McpSpec(
        'Read event log retention settings',
        'Returns configured retention days and whether stale events suggest the purge job is behind.',
        'Read-only.',
    ),
}
