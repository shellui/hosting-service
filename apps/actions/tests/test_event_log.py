import io
import tarfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.actions.emit import emit_event
from apps.actions.models import ActionOutbox, ActionRule, EventLog
from apps.actions.retention import purge_expired_data, retention_status
from apps.actions.tests.test_actions_admin_api import make_token
from apps.hosting.models import AccessStatus, CompanyHostingAccess, DeploymentStatus
from apps.hosting.services import (
    HostingError,
    create_app,
    create_deployment,
    delete_app,
    finalize_deployment,
    upload_deployment_artifact,
)


def _log(company_id=10, event_type='hosting.app.created', *, days_ago=0.0, user_id=None, data=None):
    return EventLog.objects.create(
        company_id=company_id,
        user_id=user_id,
        event_type=event_type,
        data=data or {},
        created_at=timezone.now() - timedelta(days=days_ago),
    )


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class RecordEventTests(TestCase):
    def test_emit_records_event_without_webhook_rule(self):
        emit_event(
            'hosting.app.created',
            10,
            {'app_id': 'a1', 'name': 'demo', 'display_name': '', 'company_id': 10},
            actor={'user_id': 7},
        )
        row = EventLog.objects.get()
        self.assertEqual((row.company_id, row.user_id), (10, 7))
        self.assertEqual(row.data, {'app_id': 'a1', 'name': 'demo'})
        self.assertEqual(ActionOutbox.objects.count(), 0)


@override_settings(HOSTING_DEBUG_OPEN=True, HOSTING_MAX_EXTRACT_FILE_BYTES=50)
class HostingLifecycleEventTests(TestCase):
    """Every hosting event lands in the log, linked to the user who triggered it."""

    def setUp(self):
        CompanyHostingAccess.objects.create(company_id=1, status=AccessStatus.APPROVED)

    def _deploy(self, app, files):
        deployment = create_deployment(
            app=app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=7,
            actor_email='ada@acme.test',
        )
        tarball = _tarball(files)
        upload_deployment_artifact(deployment=deployment, fileobj=io.BytesIO(tarball), content_length=len(tarball))
        return deployment

    def test_app_and_deployment_lifecycle(self):
        app = create_app(company_id=1, name='demo', display_name='Demo', user_id=7, actor_email='ada@acme.test')
        self._deploy(app, {'index.html': b'<html></html>'})
        finalize_deployment(deployment=app.deployments.get(), user_id=8, actor_email='bob@acme.test')
        bad = self._deploy(app, {'big.bin': b'x' * 51})
        with self.assertRaises(HostingError):
            finalize_deployment(deployment=bad)
        delete_app(app, user_id=7, actor_email='ada@acme.test')

        rows = list(
            EventLog.objects.order_by('pk').values_list('event_type', 'user_id', 'data__actor_email', 'data__status')
        )
        self.assertEqual(
            rows,
            [
                ('hosting.app.created', 7, 'ada@acme.test', None),
                ('hosting.deployment.created', 7, 'ada@acme.test', 'draft'),
                ('hosting.deployment.succeeded', 8, 'bob@acme.test', 'active'),
                ('hosting.deployment.created', 7, 'ada@acme.test', 'draft'),
                # Finalized without a caller: falls back to the deployer, whose email is unknown.
                ('hosting.deployment.failed', 7, None, 'failed'),
                ('hosting.app.deleted', 7, 'ada@acme.test', None),
            ],
        )

    def test_failed_deployment_status_survives_the_error(self):
        app = create_app(company_id=1, name='demo', display_name='Demo')
        bad = self._deploy(app, {'big.bin': b'x' * 51})
        with self.assertRaises(HostingError):
            finalize_deployment(deployment=bad)
        bad.refresh_from_db()
        self.assertEqual(bad.status, DeploymentStatus.FAILED)


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    IDENTITY_SERVICE_URL='',
    HOSTING_DEBUG_OPEN=True,
    HOSTING_RATE_LIMIT_ENABLED=False,
    HOSTING_MAX_EXTRACT_FILE_BYTES=50,
)
class HostingApiEventTests(TestCase):
    """Each hosting REST endpoint that changes state records its event with the caller."""

    def setUp(self):
        CompanyHostingAccess.objects.create(company_id=10, status=AccessStatus.APPROVED)
        self.client = APIClient()
        jwks_patch = patch('apps.authapi.authentication.get_jwks_client')
        jwks_patch.start().return_value.get_signing_key.return_value = None
        self.addCleanup(jwks_patch.stop)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {make_token(user_id=7, company_id=10)}')

    def _deploy(self, app_id, files):
        res = self.client.post(
            f'/hosting/v1/apps/{app_id}/deployments',
            {'app_version': '1.0.0', 'shellui_version': '0.5.0'},
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.content)
        deployment_id = res.data['id']
        upload = io.BytesIO(_tarball(files))
        upload.name = 'site.tar.gz'
        res = self.client.put(
            f'/hosting/v1/apps/{app_id}/deployments/{deployment_id}/upload',
            {'file': upload},
            format='multipart',
        )
        self.assertEqual(res.status_code, 200, res.content)
        return self.client.post(f'/hosting/v1/apps/{app_id}/deployments/{deployment_id}/finalize')

    def test_every_endpoint_records_its_event(self):
        res = self.client.post('/hosting/v1/apps', {'name': 'demo', 'display_name': 'Demo'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        app_id = res.data['id']
        self.assertEqual(self._deploy(app_id, {'index.html': b'<html></html>'}).status_code, 200)
        self.assertEqual(self._deploy(app_id, {'big.bin': b'x' * 51}).status_code, 400)
        res = self.client.post(
            '/hosting/v1/preview',
            {'display_name': 'Preview', 'app_version': '1.0.0', 'shellui_version': '0.5.0'},
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(self.client.delete(f'/hosting/v1/apps/{app_id}').status_code, 204)

        self.assertEqual(
            list(EventLog.objects.order_by('pk').values_list('event_type', flat=True)),
            [
                'hosting.app.created',
                'hosting.deployment.created',
                'hosting.deployment.succeeded',
                'hosting.deployment.created',
                'hosting.deployment.failed',
                'hosting.app.created',
                'hosting.deployment.created',
                'hosting.app.deleted',
            ],
        )
        self.assertEqual(
            set(EventLog.objects.values_list('company_id', 'user_id', 'data__actor_email')),
            {(10, 7, 'owner@acme.test')},
        )


class DjangoAdminAppDeleteTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        CompanyHostingAccess.objects.create(company_id=1, status=AccessStatus.APPROVED)
        admin = get_user_model().objects.create_superuser('root', 'root@acme.test', 'pw')
        self.client.force_login(admin)

    def test_delete_and_bulk_delete_record_events(self):
        with override_settings(HOSTING_DEBUG_OPEN=True):
            one = create_app(company_id=1, name='one', display_name='One')
            two = create_app(company_id=1, name='two', display_name='Two')
        EventLog.objects.all().delete()

        res = self.client.post(f'/admin/hosting/app/{one.pk}/delete/', {'post': 'yes'})
        self.assertEqual(res.status_code, 302)
        res = self.client.post(
            '/admin/hosting/app/',
            {'action': 'delete_selected', '_selected_action': [two.pk], 'post': 'yes'},
        )
        self.assertEqual(res.status_code, 302)

        self.assertEqual(
            sorted(EventLog.objects.values_list('event_type', 'data__name')),
            [('hosting.app.deleted', 'one'), ('hosting.app.deleted', 'two')],
        )


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
)
class EventLogApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        jwks_patch = patch('apps.authapi.authentication.get_jwks_client')
        jwks_patch.start().return_value.get_signing_key.return_value = None
        self.addCleanup(jwks_patch.stop)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {make_token(company_id=10)}')

    def _get(self, path, **params):
        return self.client.get(f'/api/v1/actions/event-log{path}', params)

    def test_list_filters_and_scope(self):
        old = _log(days_ago=2, user_id=7)
        failed = _log(event_type='hosting.deployment.failed')
        _log(company_id=99)
        response = self._get('')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r['id'] for r in response.data['results']], [failed.pk, old.pk])
        self.assertEqual(response.data['results'][0]['label'], 'Deployment failed')
        self.assertEqual([r['id'] for r in self._get('', user_id=7).data['results']], [old.pk])
        self.assertEqual(
            [r['id'] for r in self._get('', event_type='hosting.deployment.failed').data['results']],
            [failed.pk],
        )
        self.assertEqual(self._get('', event_type='nope').status_code, 400)

    def test_detail_types_and_retention(self):
        mine = _log()
        theirs = _log(company_id=99)
        self.assertEqual(self._get(f'/{mine.pk}').status_code, 200)
        self.assertEqual(self._get(f'/{theirs.pk}').status_code, 404)
        self.assertIn('hosting.deployment.failed', {r['type'] for r in self._get('/types').data['results']})
        self.assertFalse(self._get('/retention').data['stale_events'])
        _log(days_ago=8.5)
        self.assertTrue(self._get('/retention').data['stale_events'])

    def test_non_owner_is_forbidden(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {make_token(is_company_owner=False)}')
        self.assertEqual(self._get('').status_code, 403)


class PurgeExpiredDataTests(TestCase):
    def setUp(self):
        rule = ActionRule.objects.create(
            company_id=10,
            name='Hook',
            event_type='hosting.app.created',
            config={'url': 'https://example.com/hook'},
        )
        ActionOutbox.objects.create(
            company_id=10, action_rule=rule, event_type='x', envelope={}, status=ActionOutbox.STATUS_DEAD
        )
        self.pending = ActionOutbox.objects.create(
            company_id=10, action_rule=rule, event_type='x', envelope={}, status=ActionOutbox.STATUS_PENDING
        )
        ActionOutbox.objects.update(created_at=timezone.now() - timedelta(days=10))

    def test_purge_and_command(self):
        _log(days_ago=8)
        kept = _log(days_ago=6)
        self.assertEqual(purge_expired_data(dry_run=True)['events'], 1)
        out = StringIO()
        call_command('purge_expired_data', '--batch-size', '1', stdout=out)
        self.assertIn('deleted events=1 webhook_deliveries=1 complete=true', out.getvalue())
        self.assertEqual(list(EventLog.objects.values_list('pk', flat=True)), [kept.pk])
        self.assertEqual(list(ActionOutbox.objects.values_list('pk', flat=True)), [self.pending.pk])

    @override_settings(EVENT_LOG_RETENTION_DAYS=30)
    def test_retention_setting(self):
        _log(days_ago=8)
        self.assertEqual(purge_expired_data()['events'], 0)
        self.assertEqual(retention_status(10)['data_retention_days'], 30)
