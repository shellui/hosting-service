"""DRF serializers for OpenAPI documentation."""

from rest_framework import serializers


class ErrorSerializer(serializers.Serializer):
    statusCode = serializers.CharField(required=False)
    error = serializers.CharField(required=False)
    message = serializers.CharField()
    request_id = serializers.CharField(required=False)


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    version = serializers.CharField()
    hosting_backend = serializers.CharField()
    identity_jwks_source = serializers.CharField()
    identity_jwks_url = serializers.CharField(allow_null=True)


class AccessSerializer(serializers.Serializer):
    company_id = serializers.IntegerField()
    status = serializers.CharField()
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
    id = serializers.UUIDField()
    name = serializers.SlugField()
    slug = serializers.SlugField()
    company_id = serializers.IntegerField()
    display_name = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    current_deployment_id = serializers.UUIDField(allow_null=True)
    urls = serializers.DictField(required=False)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class AppCreateSerializer(serializers.Serializer):
    name = serializers.SlugField()
    display_name = serializers.CharField(required=False, allow_blank=True)


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


class DeploymentCreateSerializer(serializers.Serializer):
    app_version = serializers.CharField()
    shellui_version = serializers.CharField()
    pinned = serializers.BooleanField(required=False, default=False)


class PreviewPrepareSerializer(serializers.Serializer):
    slug = serializers.SlugField(required=False, allow_blank=True)
    display_name = serializers.CharField(required=False, allow_blank=True)
    app_version = serializers.CharField()
    shellui_version = serializers.CharField()


class PreviewPrepareResponseSerializer(serializers.Serializer):
    app = AppSerializer()
    deployment = DeploymentSerializer()
    slug = serializers.SlugField()
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    urls = serializers.DictField(required=False)
