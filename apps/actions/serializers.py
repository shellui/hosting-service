from rest_framework import serializers

from apps.authapi.mcp_fields import McpSecretCharField
from apps.actions.models import ActionRule
from apps.actions.registry import is_webhook_event


class ActionRuleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=200,
        required=False,
        help_text='Rule name shown in the Shellui Actions list.',
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='Optional note about what this rule is for.',
    )
    event_type = serializers.CharField(
        max_length=128,
        required=False,
        help_text='Shellui Actions event id this rule subscribes to.',
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text='When false, the rule does not send webhooks.',
    )

    url = serializers.URLField(
        required=False,
        allow_blank=True,
        help_text='HTTPS endpoint that receives the signed webhook.',
    )
    secret = McpSecretCharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text='Optional signing secret. Omit it and Shellui generates one.',
    )
    authorization_header = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text='Optional Authorization header value sent with the webhook.',
    )
    allow_private_urls = serializers.BooleanField(
        required=False,
        help_text='Staff only. Allow a private or loopback webhook URL.',
    )

    def validate_event_type(self, value):
        if value and not is_webhook_event(value):
            raise serializers.ValidationError('Unknown event type.')
        return value


class ActionRuleCreateSerializer(ActionRuleWriteSerializer):
    name = serializers.CharField(
        max_length=200,
        help_text='Rule name shown in the Shellui Actions list.',
    )
    event_type = serializers.CharField(
        max_length=128,
        help_text='Shellui Actions event id this rule subscribes to.',
    )
    url = serializers.URLField(help_text='HTTPS endpoint that receives the signed webhook.')

    def validate_event_type(self, value):
        if not is_webhook_event(value):
            raise serializers.ValidationError('Unknown event type.')
        return value


class ActionRuleUpdateSerializer(ActionRuleWriteSerializer):
    pass
