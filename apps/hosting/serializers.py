"""DRF serializers for OpenAPI documentation."""

from rest_framework import serializers

from apps.authapi.mcp_fields import McpSecretCharField, McpSensitiveCharField


class ErrorSerializer(serializers.Serializer):
    statusCode = serializers.CharField(
        required=False,
        help_text='HTTP status as a string (for example `400`, `404`).',
    )
    error = serializers.CharField(
        required=False,
        help_text='Stable machine code (for example `forbidden`, `deployment_not_found`, `rate_limited`).',
    )
    message = serializers.CharField(
        help_text='Human-readable detail. Prefer `error` for programmatic handling.',
    )
    field_errors = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
        help_text='Optional map of field names to stable validation tokens (for example `required`, `invalid`).',
    )
    request_id = serializers.CharField(
        required=False,
        help_text='Echo of the `X-Request-ID` header when present.',
    )


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    version = serializers.CharField()
    hosting_backend = serializers.CharField()
    identity_jwks_source = serializers.CharField()
    identity_jwks_url = serializers.CharField(allow_null=True)


class AccessSerializer(serializers.Serializer):
    company_id = serializers.IntegerField(help_text='Shellui company id.')
    status = serializers.ChoiceField(
        choices=['pending', 'approved', 'denied'],
        help_text='Hosting access state. Deploy APIs require `approved`.',
    )
    requested_at = serializers.DateTimeField(allow_null=True)
    requested_by_id = serializers.IntegerField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    reviewed_by_id = serializers.IntegerField(allow_null=True)
    notes = serializers.CharField()


class AccessUpdateSerializer(serializers.Serializer):
    company_id = serializers.IntegerField(required=False)
    status = serializers.ChoiceField(choices=['pending', 'approved', 'denied'])
    notes = serializers.CharField(required=False, allow_blank=True)


class AppSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text='App UUID.')
    name = serializers.SlugField(help_text='Internal slug (same as public slug).')
    slug = serializers.SlugField(help_text='Public site slug used in URLs.')
    company_id = serializers.IntegerField()
    display_name = serializers.CharField(help_text='Human label shown in admin.')
    expires_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text='Preview expiry (ISO 8601). Null for production sites. Previews last 7 days after each finalize.',
    )
    current_deployment_id = serializers.UUIDField(allow_null=True)
    urls = serializers.DictField(required=False)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class AppCreateSerializer(serializers.Serializer):
    name = serializers.SlugField(help_text='Unique slug under the company (lowercase, hyphens).')
    display_name = serializers.CharField(required=False, allow_blank=True, help_text='Optional display label.')


class DeploymentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    app_id = serializers.UUIDField()
    app_version = serializers.CharField()
    shellui_version = serializers.CharField()
    status = serializers.CharField()
    pinned = serializers.BooleanField()
    storage_prefix = serializers.CharField()
    deployed_by_id = serializers.IntegerField(allow_null=True)
    artifact_size = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    finalized_at = serializers.DateTimeField(allow_null=True)
    oauth_redirect_registered = serializers.BooleanField(required=False)
    oauth_redirect_origin = serializers.CharField(required=False, allow_blank=True)
    oauth_redirect_warning = serializers.CharField(required=False, allow_blank=True)


class ArtifactUploadUrlResponseSerializer(serializers.Serializer):
    upload_url = McpSensitiveCharField(
        help_text='HTTPS URL for a raw PUT of the `.tar.gz` artifact. Treat as a secret when using S3 presigned URLs.',
    )
    method = serializers.CharField(help_text='HTTP method for the upload (`PUT`).')
    headers = serializers.DictField(
        child=serializers.CharField(),
        help_text='Headers to send with the upload (for example `Content-Type: application/gzip`).',
    )
    requires_bearer = serializers.BooleanField(
        help_text='When true, repeat the same `Authorization: Bearer` agent token on the PUT request.',
    )
    expires_at = serializers.DateTimeField(help_text='UTC expiry for the upload URL.')
    backend = serializers.ChoiceField(
        choices=['s3', 'direct'],
        help_text='`s3` uses a presigned object URL. `direct` PUTs to hosting-service with your agent token.',
    )


class DeploymentCreateSerializer(serializers.Serializer):
    app_version = serializers.CharField(help_text='Semver of your app build (for example `1.2.3`).')
    shellui_version = serializers.CharField(help_text='Shellui framework version bundled in the artifact.')
    pinned = serializers.BooleanField(
        required=False,
        default=False,
        help_text='When true, rollback skips this deployment unless explicitly selected.',
    )


class PreviewPrepareSerializer(serializers.Serializer):
    slug = serializers.SlugField(
        required=False,
        allow_blank=True,
        help_text='Optional preview slug. Omit to allocate a new slug.',
    )
    display_name = serializers.CharField(required=False, allow_blank=True)
    app_version = serializers.CharField(help_text='Semver of the preview build.')
    shellui_version = serializers.CharField(help_text='Shellui framework version in the bundle.')


class PreviewPrepareResponseSerializer(serializers.Serializer):
    app = AppSerializer()
    deployment = DeploymentSerializer()
    slug = serializers.SlugField()
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    urls = serializers.DictField(required=False)
    oauth_redirect_registered = serializers.BooleanField(required=False)
    oauth_redirect_origin = serializers.CharField(required=False, allow_blank=True)
    oauth_redirect_warning = serializers.CharField(required=False, allow_blank=True)


class DeployTokenSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    prefix = serializers.CharField()
    created_by_id = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()
    last_used_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)


class DeployTokenCreateResponseSerializer(DeployTokenSerializer):
    token = McpSecretCharField(
        required=False,
        help_text='Plaintext deploy token. Returned once on create; stored hashed server-side.',
    )


class CustomDomainDnsSerializer(serializers.Serializer):
    verification_txt_name = serializers.CharField(help_text='TXT record name relative to the hostname (underscore label).')
    verification_txt_value = serializers.CharField(help_text='TXT value to publish for DNS verification.')


class CustomDomainSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    app_id = serializers.UUIDField()
    hostname = serializers.CharField()
    status = serializers.ChoiceField(choices=['pending_dns', 'awaiting_platform', 'active'])
    verified = serializers.BooleanField(
        help_text='True only after the platform confirms DNS. Always false until edge integration ships.'
    )
    serving = serializers.BooleanField(
        help_text='True only when the edge serves TLS for this hostname. Always false in this release.'
    )
    dns = CustomDomainDnsSerializer()
    instructions = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class CustomDomainCreateSerializer(serializers.Serializer):
    hostname = serializers.CharField(
        max_length=253,
        help_text='Fully qualified hostname (not under the default app hosting domain).',
    )


class EnvVariableListSerializer(serializers.Serializer):
    key = serializers.CharField()
    value_present = serializers.BooleanField(help_text='Whether a value is stored. Values are never returned.')
    updated_at = serializers.DateTimeField()


class EnvVariableUpsertSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=128, help_text='Must match /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.')
    value = McpSecretCharField(help_text='New value. Never echoed in list or get responses.')


class EnvVariableValueSerializer(serializers.Serializer):
    value = McpSecretCharField(help_text='New value. Never echoed in list or get responses.')


class EnvVariableKeySerializer(serializers.Serializer):
    key = serializers.CharField(max_length=128)


class RequestLogEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    method = serializers.CharField()
    path = serializers.CharField(help_text='Request path and query only; query values are not redacted.')
    status_code = serializers.IntegerField()
    request_id = serializers.CharField(allow_null=True, required=False)


class RequestLogListResponseSerializer(serializers.Serializer):
    results = RequestLogEntrySerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True, required=False)
    limit = serializers.IntegerField()


class RuntimeLogResponseSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=['none'])
    unavailable_reason = serializers.CharField()
    lines = serializers.ListField(child=serializers.CharField())
    truncated = serializers.BooleanField()
    limit = serializers.IntegerField()
