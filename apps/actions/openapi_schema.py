"""DRF serializers used only for OpenAPI (Actions admin API)."""

from rest_framework import serializers

from apps.authapi.mcp_fields import McpSecretCharField


class ActionsErrorSerializer(serializers.Serializer):
    error = serializers.CharField(
        help_text='Stable machine code or short reason (for example `Not found.`, `Forbidden`).',
    )


class ActionEventTypeSerializer(serializers.Serializer):
    type = serializers.CharField(help_text='Catalog event id (for example `hosting.deployment.finalized`).')
    label = serializers.CharField()
    description = serializers.CharField()
    emit_by_default = serializers.BooleanField()
    supported_action_kinds = serializers.ListField(child=serializers.CharField())
    payload_fields = serializers.ListField(child=serializers.DictField())
    sample_envelope = serializers.DictField()


class ActionEventListSerializer(serializers.Serializer):
    results = ActionEventTypeSerializer(many=True)


class ActionRuleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField()
    event_type = serializers.CharField()
    enabled = serializers.BooleanField()
    action_kind = serializers.CharField()
    config = serializers.DictField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    secret = McpSecretCharField(
        required=False,
        help_text='Plaintext signing secret. Returned once on create or rotate only.',
    )


class ActionRuleListSerializer(serializers.Serializer):
    results = ActionRuleSerializer(many=True)


class ActionTestResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField(required=False)
    status_code = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False)


class DeliveryAttemptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    http_status = serializers.IntegerField(allow_null=True)
    error_message = serializers.CharField(allow_blank=True)
    attempt_number = serializers.IntegerField()
    duration_ms = serializers.IntegerField(allow_null=True)
    trigger = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class DeliverySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    company_id = serializers.IntegerField()
    action_rule_id = serializers.IntegerField(allow_null=True)
    action_rule_name = serializers.CharField()
    action_kind = serializers.CharField()
    event_type = serializers.CharField()
    status = serializers.CharField()
    attempt_count = serializers.IntegerField()
    next_attempt_at = serializers.DateTimeField(allow_null=True)
    last_error = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    delivered_at = serializers.DateTimeField(allow_null=True)


class DeliveryDetailSerializer(DeliverySerializer):
    attempts = DeliveryAttemptSerializer(many=True)
    envelope = serializers.DictField()


class DeliveryListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    results = DeliverySerializer(many=True)


class EventLogRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    company_id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    event_type = serializers.CharField()
    label = serializers.CharField()
    user_id = serializers.IntegerField(allow_null=True)
    user_email = serializers.EmailField(required=False, allow_null=True)
    data = serializers.DictField()


class EventLogListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    results = EventLogRowSerializer(many=True)


class EventLogTypeSerializer(serializers.Serializer):
    type = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    webhook = serializers.BooleanField()


class EventLogTypesSerializer(serializers.Serializer):
    results = EventLogTypeSerializer(many=True)


class EventLogRetentionSerializer(serializers.Serializer):
    data_retention_days = serializers.IntegerField()
    oldest_event_at = serializers.DateTimeField(allow_null=True)
    stale_events = serializers.BooleanField()
