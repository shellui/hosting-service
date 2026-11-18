"""Hosting metadata models — deployment artifacts live in the configured storage backend."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class AccessStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    DENIED = 'denied', 'Denied'


class CompanyHostingAccess(models.Model):
    """Waitlist / approval gate for company hosting."""

    company_id = models.PositiveIntegerField(unique=True, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=AccessStatus.choices,
        default=AccessStatus.PENDING,
        db_index=True,
    )
    requested_by_id = models.PositiveIntegerField(null=True, blank=True)
    requested_at = models.DateTimeField(default=timezone.now)
    reviewed_by_id = models.PositiveIntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=512, blank=True, default='')

    class Meta:
        verbose_name = 'company hosting access'
        verbose_name_plural = 'company hosting access'

    def __str__(self) -> str:
        return f'company={self.company_id} status={self.status}'


class DeploymentStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    UPLOADING = 'uploading', 'Uploading'
    READY = 'ready', 'Ready'
    ACTIVE = 'active', 'Active'
    SUPERSEDED = 'superseded', 'Superseded'
    FAILED = 'failed', 'Failed'


class App(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.SlugField(max_length=63, db_index=True)
    slug = models.SlugField(max_length=63, unique=True, db_index=True)
    company_id = models.PositiveIntegerField(db_index=True)
    display_name = models.CharField(max_length=200)
    created_by_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    current_deployment = models.ForeignKey(
        'Deployment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company_id', 'name'], name='hosting_app_company_name_uniq'),
        ]
        indexes = [
            models.Index(fields=['company_id', 'name']),
        ]
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class Deployment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='deployments')
    app_version = models.CharField(max_length=64)
    shellui_version = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=DeploymentStatus.choices,
        default=DeploymentStatus.DRAFT,
        db_index=True,
    )
    pinned = models.BooleanField(default=False)
    storage_prefix = models.CharField(max_length=512)
    deployed_by_id = models.PositiveIntegerField(null=True, blank=True)
    artifact_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['app', 'status']),
            models.Index(fields=['app', 'created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.app.name}@{self.app_version} ({self.status})'


class DeployToken(models.Model):
    """Company CI token for preview deploys. Only a sha256 hash is stored; the raw token is shown once."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.PositiveIntegerField(db_index=True)
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=24, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    created_by_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.name} ({self.prefix}...)'


class CustomDomainStatus(models.TextChoices):
    """Local registration state. Serving still uses slug-based DNS until edge integration exists."""

    PENDING_DNS = 'pending_dns', 'Pending DNS'
    AWAITING_PLATFORM = 'awaiting_platform', 'Awaiting platform'
    ACTIVE = 'active', 'Active'


class AppCustomDomain(models.Model):
    """Custom hostname a company wants to point at a hosted app. Verification is DNS-based metadata only."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='custom_domains')
    hostname = models.CharField(max_length=253, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=CustomDomainStatus.choices,
        default=CustomDomainStatus.PENDING_DNS,
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['app', 'hostname'], name='hosting_app_custom_domain_app_host_uniq'),
            models.UniqueConstraint(fields=['hostname'], name='hosting_custom_domain_hostname_global_uniq'),
        ]
        indexes = [
            models.Index(fields=['app', 'status']),
        ]
        ordering = ['hostname']

    def __str__(self) -> str:
        return f'{self.hostname} ({self.status})'


class AppEnvironmentVariable(models.Model):
    """Key/value for build-time metadata and future runtime injection (values encrypted at rest)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='environment_variables')
    key = models.CharField(max_length=128, db_index=True)
    value_ciphertext = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['app', 'key'], name='hosting_app_env_key_uniq'),
        ]
        ordering = ['key']

    def __str__(self) -> str:
        return self.key


class HostedAppRequestLog(models.Model):
    """Bounded HTTP access log lines recorded on the app hostname only."""

    id = models.BigAutoField(primary_key=True)
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='request_logs')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    method = models.CharField(max_length=16)
    path = models.CharField(max_length=2048)
    status_code = models.PositiveSmallIntegerField()
    request_id = models.CharField(max_length=128, blank=True, default='')

    class Meta:
        indexes = [
            models.Index(fields=['app', '-created_at']),
        ]
        ordering = ['-created_at', '-id']
