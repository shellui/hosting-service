"""Register hosting-service domain events (``hosting.*`` prefix)."""

from apps.actions.registry import DomainEventType, EventFieldDoc, register_event

_APP = (
    EventFieldDoc('app_id', 'Hosted app UUID', '550e8400-e29b-41d4-a716-446655440000'),
    EventFieldDoc('name', 'Company-scoped app name (slug)', 'my-app'),
    EventFieldDoc('slug', 'Public hosting slug (subdomain)', 'abc12345'),
    EventFieldDoc('display_name', 'Human-readable label', 'My App'),
    EventFieldDoc('company_id', 'Identity company id', 1),
)

_DEPLOYMENT = _APP + (
    EventFieldDoc('deployment_id', 'Deployment UUID', '660e8400-e29b-41d4-a716-446655440001'),
    EventFieldDoc('app_version', 'App semver from the artifact', '1.0.0'),
    EventFieldDoc('shellui_version', 'Shellui semver from the artifact', '0.4.0'),
    EventFieldDoc('status', 'Deployment status after the event', 'active'),
)

register_event(
    DomainEventType(
        id='hosting.app.created',
        label='Hosted app created',
        description='A new hosted app record was created for the company.',
        payload_fields=_APP,
    )
)

register_event(
    DomainEventType(
        id='hosting.app.deleted',
        label='Hosted app deleted',
        description='A hosted app and its deployments were removed.',
        payload_fields=_APP,
    )
)

register_event(
    DomainEventType(
        id='hosting.deployment.created',
        label='Deployment created',
        description='A new deployment row was created (draft, ready for artifact upload).',
        payload_fields=_DEPLOYMENT + (EventFieldDoc('status', 'Initial status', 'draft'),),
    )
)

register_event(
    DomainEventType(
        id='hosting.deployment.succeeded',
        label='Deployment succeeded',
        description='Artifact upload and extract finished; deployment is active and serving traffic.',
        payload_fields=_DEPLOYMENT + (EventFieldDoc('status', 'Status after finalize', 'active'),),
    )
)

register_event(
    DomainEventType(
        id='hosting.deployment.failed',
        label='Deployment failed',
        description='Finalize or extract failed; deployment status is failed.',
        payload_fields=_DEPLOYMENT
        + (
            EventFieldDoc('status', 'Status after failure', 'failed'),
            EventFieldDoc('error', 'Short failure reason when available', 'artifact_extract_failed'),
        ),
    )
)

_DOMAIN = _APP + (
    EventFieldDoc('domain_id', 'Custom domain UUID', '770e8400-e29b-41d4-a716-446655440002'),
    EventFieldDoc('hostname', 'Requested hostname', 'app.example.com'),
    EventFieldDoc('status', 'Workflow status on hosting-service', 'pending_dns'),
)

register_event(
    DomainEventType(
        id='hosting.custom_domain.created',
        label='Custom domain registered',
        description='A custom hostname row was created for the app. DNS is not verified until the platform confirms.',
        payload_fields=_DOMAIN,
    )
)

register_event(
    DomainEventType(
        id='hosting.custom_domain.updated',
        label='Custom domain status refreshed',
        description='Hosting-service re-evaluated DNS or refresh metadata for a custom hostname.',
        payload_fields=_DOMAIN,
    )
)

register_event(
    DomainEventType(
        id='hosting.custom_domain.deleted',
        label='Custom domain removed',
        description='A custom hostname row was deleted for the app.',
        payload_fields=_DOMAIN,
    )
)

_ENV = _APP + (EventFieldDoc('key', 'Environment variable name', 'BUILD_ID'),)

register_event(
    DomainEventType(
        id='hosting.environment_variable.created',
        label='App environment variable created',
        description='A new app-scoped environment variable was stored (value never appears in APIs).',
        payload_fields=_ENV,
    )
)

register_event(
    DomainEventType(
        id='hosting.environment_variable.updated',
        label='App environment variable updated',
        description='An app-scoped environment variable value was replaced.',
        payload_fields=_ENV,
    )
)

register_event(
    DomainEventType(
        id='hosting.environment_variable.deleted',
        label='App environment variable deleted',
        description='An app-scoped environment variable was removed.',
        payload_fields=_ENV,
    )
)

# Platform events: one per finished scheduled job run. No company, staff only, never sent
# to webhooks or email-service. See docs/maintenance-jobs.md.
_SCHEDULED_JOB = (
    EventFieldDoc('run_id', 'ScheduledJobRun id', 1234),
    EventFieldDoc('job', 'Job name: retry_webhooks or purge_expired_data', 'retry_webhooks'),
    EventFieldDoc('trigger', 'celery (in-container beat) or command (external scheduler)', 'celery'),
    EventFieldDoc('duration_ms', 'Run duration in milliseconds', 412),
    EventFieldDoc(
        'counts',
        'Items processed, per kind',
        {'webhook_deliveries_attempted': 3, 'webhook_deliveries_succeeded': 3},
    ),
    EventFieldDoc('host', 'Host name and process id that ran the job', 'hosting-7f9c:41'),
)

register_event(
    DomainEventType(
        id='hosting.scheduled_job.succeeded',
        label='Scheduled job succeeded',
        description='A scheduled job run finished without error. Platform event, staff only.',
        payload_fields=_SCHEDULED_JOB,
        webhook=False,
        staff_only=True,
    )
)

register_event(
    DomainEventType(
        id='hosting.scheduled_job.failed',
        label='Scheduled job failed',
        description='A scheduled job run raised an error. Platform event, staff only.',
        payload_fields=_SCHEDULED_JOB
        + (
            EventFieldDoc('error_key', 'Stable error key (database_error, redis_error, …)', 'database_error'),
            EventFieldDoc('error_class', 'Exception class name', 'OperationalError'),
        ),
        webhook=False,
        staff_only=True,
    )
)
