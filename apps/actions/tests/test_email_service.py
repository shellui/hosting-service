"""email-service event forwarding on the webhook outbox."""

from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.actions.emit import emit_event
from apps.actions.models import ActionOutbox, ActionRule, DeliveryAttempt
from apps.actions.tests.test_actions_admin_api import make_token

API_KEY = 'esk_test_hosting_key_do_not_use'  # gitleaks:allow

EMAIL_SETTINGS = {
    'EMAIL_SERVICE_URL': 'https://email.shellui.com',
    'EMAIL_SERVICE_API_KEY': API_KEY,
    'ACTIONS_WEBHOOK_SYNC_DELIVERY': True,
}


class _Response:
    def __init__(self, status, text='', retry_after=None):
        self.status_code = status
        self.text = text
        self.headers = {}
        if retry_after is not None:
            self.headers['Retry-After'] = str(retry_after)


def _failed_payload():
    return {
        'app_id': '550e8400-e29b-41d4-a716-446655440000',
        'name': 'my-app',
        'slug': 'abc12345',
        'display_name': 'My App',
        'company_id': 42,
        'deployment_id': '660e8400-e29b-41d4-a716-446655440001',
        'app_version': '1.2.0',
        'shellui_version': '0.4.0',
        'status': 'failed',
        'error': 'artifact_extract_failed',
    }


@override_settings(**EMAIL_SETTINGS)
class EmailForwardingTests(TestCase):
    def setUp(self):
        self.company_id = 42
        self.actor = {'user_id': 7, 'email': 'ada@acme.com'}

    @patch('apps.actions.email_service.requests.post', return_value=_Response(202, '{"messages":[]}'))
    def test_forwards_event_with_contract_shape(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            rows = emit_event(
                'hosting.deployment.failed',
                self.company_id,
                _failed_payload(),
                actor=self.actor,
            )
        self.assertEqual(rows, [])
        row = ActionOutbox.objects.get()
        self.assertEqual(row.delivery_kind, ActionOutbox.KIND_EMAIL)
        self.assertIsNone(row.action_rule_id)
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)

        self.assertEqual(mock_post.call_args.args[0], 'https://email.shellui.com/api/v1/events')
        headers = mock_post.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], f'Bearer {API_KEY}')
        self.assertFalse(mock_post.call_args.kwargs['allow_redirects'])
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body['service'], 'hosting')
        self.assertEqual(body['event_type'], 'hosting.deployment.failed')
        self.assertEqual(body['company_id'], 42)
        self.assertNotIn('language', body)
        self.assertEqual(body['payload']['display_name'], 'My App')
        self.assertEqual(body['payload']['app_version'], '1.2.0')
        self.assertEqual(body['payload']['error'], 'artifact_extract_failed')
        self.assertEqual(body['recipients'], [{'email': 'ada@acme.com', 'user_id': 7}])
        self.assertEqual(body['idempotency_key'], row.envelope['idempotency_key'])
        self.assertNotIn(API_KEY, str(body))

    @patch('apps.actions.email_service.requests.post', return_value=_Response(202))
    def test_does_not_post_before_commit(self, mock_post):
        with self.captureOnCommitCallbacks(execute=False):
            emit_event(
                'hosting.app.created',
                self.company_id,
                {'display_name': 'My App', 'name': 'my-app', 'slug': 'abc12345'},
                actor=self.actor,
            )
        mock_post.assert_not_called()
        self.assertEqual(ActionOutbox.objects.count(), 1)

    @patch('apps.actions.handlers.webhook.post_webhook_url')
    @patch('apps.actions.email_service.requests.post', return_value=_Response(202))
    def test_webhook_rows_stay_separate(self, mock_email, mock_webhook):
        from apps.actions.webhook_transport import WebhookPostResult

        mock_webhook.return_value = WebhookPostResult(status=200, excerpt='')
        ActionRule.objects.create(
            company_id=self.company_id,
            name='Hook',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            config={'url': 'https://example.com/hook', 'secret': 'plain-secret'},
        )
        with self.captureOnCommitCallbacks(execute=True):
            rows = emit_event(
                'hosting.app.created',
                self.company_id,
                {'display_name': 'My App', 'name': 'my-app'},
                actor={'email': 'ada@acme.com'},
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].delivery_kind, ActionOutbox.KIND_WEBHOOK)
        self.assertEqual(ActionOutbox.objects.filter(delivery_kind=ActionOutbox.KIND_EMAIL).count(), 1)
        mock_email.assert_called_once()
        mock_webhook.assert_called_once()
        emailed = mock_email.call_args.kwargs['json']
        self.assertEqual(emailed['recipients'], [{'email': 'ada@acme.com'}])
        self.assertNotIn('user_id', emailed['recipients'][0])

    @patch('apps.actions.email_service.requests.post', return_value=_Response(503, 'unavailable'))
    def test_failure_retries_with_the_same_body(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event(
                'hosting.deployment.failed',
                self.company_id,
                _failed_payload(),
                actor=self.actor,
            )
        row = ActionOutbox.objects.get()
        self.assertEqual(row.status, ActionOutbox.STATUS_FAILED)
        self.assertIsNotNone(row.next_attempt_at)
        first_body = mock_post.call_args.kwargs['json']

        mock_post.return_value = _Response(202, '{"rule_enabled": true, "messages": []}')
        row.next_attempt_at = timezone.now()
        row.locked_until = None
        row.save(update_fields=['next_attempt_at', 'locked_until'])
        call_command('retry_webhooks', '--concurrency', '1')

        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)
        self.assertEqual(mock_post.call_count, 2)
        second_body = mock_post.call_args.kwargs['json']
        self.assertEqual(first_body, second_body)
        self.assertEqual(first_body['idempotency_key'], second_body['idempotency_key'])

    @patch('apps.actions.email_service.requests.post', return_value=_Response(400, '{"error_code":"validation_failed"}'))
    def test_client_error_is_not_retried(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event(
                'hosting.deployment.failed',
                self.company_id,
                _failed_payload(),
                actor=self.actor,
            )
        row = ActionOutbox.objects.get()
        self.assertEqual(row.status, ActionOutbox.STATUS_DEAD)
        call_command('retry_webhooks', '--concurrency', '1')
        self.assertEqual(mock_post.call_count, 1)
        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DEAD)

    @patch('apps.actions.email_service.requests.post', return_value=_Response(404, 'missing'))
    def test_not_found_is_retried_with_the_same_body(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event('hosting.app.deleted', self.company_id, {'display_name': 'My App'}, actor=self.actor)
        row = ActionOutbox.objects.get()
        self.assertEqual(row.status, ActionOutbox.STATUS_FAILED)
        first_body = mock_post.call_args.kwargs['json']

        mock_post.return_value = _Response(202, '{"rule_enabled": false, "skipped_reason": "rule_disabled", "messages": []}')
        row.next_attempt_at = timezone.now()
        row.locked_until = None
        row.save(update_fields=['next_attempt_at', 'locked_until'])
        call_command('retry_webhooks', '--concurrency', '1')

        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args.kwargs['json'], first_body)

    @patch(
        'apps.actions.email_service.requests.post',
        return_value=_Response(202, '{"rule_enabled": true, "skipped_reason": "no_recipients", "messages": []}'),
    )
    def test_empty_recipients_skip_is_finished(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event('hosting.deployment.failed', self.company_id, _failed_payload())
        row = ActionOutbox.objects.get()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)
        self.assertEqual(mock_post.call_args.kwargs['json']['recipients'], [])
        call_command('retry_webhooks', '--concurrency', '1')
        self.assertEqual(mock_post.call_count, 1)

    def test_permanent_statuses_match_webhook_delivery(self):
        from apps.actions.email_service import email_status_is_permanent

        for code in (400, 401, 403, 405, 410, 413, 422):
            self.assertTrue(email_status_is_permanent(code), code)
        for code in (404, 408, 409, 425, 429, 402, 500, 502, 503):
            self.assertFalse(email_status_is_permanent(code), code)
        self.assertFalse(email_status_is_permanent(None))

    @patch('apps.actions.email_service.requests.post')
    def test_api_key_is_not_logged_or_stored(self, mock_post):
        mock_post.side_effect = [
            requests.ConnectionError(f'connection failed token={API_KEY}'),
            _Response(400, f'body mentions {API_KEY}'),
        ]
        with self.assertLogs('apps', level='DEBUG') as captured:
            with self.captureOnCommitCallbacks(execute=True):
                emit_event(
                    'hosting.deployment.failed',
                    self.company_id,
                    _failed_payload(),
                    actor=self.actor,
                )
        self.assertNotIn(API_KEY, '\n'.join(captured.output))
        row = ActionOutbox.objects.get()
        self.assertNotIn(API_KEY, row.last_error)
        self.assertNotIn(API_KEY, row.envelope.get('idempotency_key', ''))
        for attempt in DeliveryAttempt.objects.filter(outbox=row):
            self.assertNotIn(API_KEY, attempt.error_message)

        row.status = ActionOutbox.STATUS_FAILED
        row.attempt_count = 0
        row.next_attempt_at = timezone.now()
        row.locked_until = None
        row.save()
        with self.assertLogs('apps', level='DEBUG') as captured_http:
            call_command('retry_webhooks', '--concurrency', '1')
        self.assertNotIn(API_KEY, '\n'.join(captured_http.output))
        row.refresh_from_db()
        self.assertNotIn(API_KEY, row.last_error)
        for attempt in DeliveryAttempt.objects.filter(outbox=row):
            self.assertNotIn(API_KEY, attempt.error_message)

    @override_settings(
        ALLOWED_HOSTS=['testserver'],
        JWT_HS256_FALLBACK_SECRET='test-secret',
        ALLOW_JWT_HS256_FALLBACK=True,
        IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    )
    def test_email_rows_are_hidden_from_the_webhook_delivery_api(self):
        with patch('apps.actions.email_service.requests.post', return_value=_Response(202)):
            with self.captureOnCommitCallbacks(execute=True):
                emit_event(
                    'hosting.app.created',
                    10,
                    {'display_name': 'My App'},
                    actor=self.actor,
                )
        email_row = ActionOutbox.objects.get(delivery_kind=ActionOutbox.KIND_EMAIL)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {make_token(company_id=10)}')
        with patch('apps.authapi.authentication.get_jwks_client') as mock_jwks:
            mock_jwks.return_value.get_signing_key.return_value = None
            listed = client.get('/api/v1/actions/deliveries')
            detail = client.get(f'/api/v1/actions/deliveries/{email_row.pk}')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data['count'], 0)
        self.assertEqual(detail.status_code, 404)


@override_settings(EMAIL_SERVICE_URL='https://email.shellui.com', EMAIL_SERVICE_API_KEY='')
class EmailUnconfiguredTests(TestCase):
    @patch('apps.actions.email_service.requests.post')
    def test_nothing_is_sent_without_an_api_key(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            rows = emit_event(
                'hosting.deployment.failed',
                42,
                _failed_payload(),
                actor={'user_id': 7, 'email': 'ada@acme.com'},
            )
        self.assertEqual(rows, [])
        mock_post.assert_not_called()
        self.assertEqual(ActionOutbox.objects.count(), 0)

    @override_settings(EMAIL_SERVICE_API_KEY='   ')
    @patch('apps.actions.email_service.requests.post')
    def test_blank_api_key_is_unconfigured(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event('hosting.app.created', 42, {'display_name': 'My App'})
        mock_post.assert_not_called()
        self.assertEqual(ActionOutbox.objects.count(), 0)

