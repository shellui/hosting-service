"""email-service event forwarding on the webhook outbox."""

import json
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.actions.email_service import EmailDeliveryError, post_email_event
from apps.actions.emit import emit_event
from apps.actions.models import ActionOutbox, ActionRule, DeliveryAttempt, EventLog
from apps.actions.tests.test_actions_admin_api import make_token
from apps.actions.webhook_transport import WebhookPostResult

API_KEY = 'esk_test_hosting_key_do_not_use'  # gitleaks:allow

EMAIL_SETTINGS = {
    'EMAIL_SERVICE_URL': 'https://email.shellui.com',
    'EMAIL_SERVICE_API_KEY': API_KEY,
    'ACTIONS_WEBHOOK_SYNC_DELIVERY': True,
}


def _result(status, text='', retry_after=None):
    return WebhookPostResult(status=status, excerpt=text, retry_after_seconds=retry_after)


def _posted_json(mock_post):
    return json.loads(mock_post.call_args.kwargs['body'])


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

    @patch('apps.actions.email_service.post_webhook_url', return_value=_result(202, '{"messages":[]}'))
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
        self.assertFalse(mock_post.call_args.kwargs['allow_private'])
        body = _posted_json(mock_post)
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

    @patch('apps.actions.handlers.webhook.post_webhook_url')
    @patch('apps.actions.email_service.post_webhook_url', return_value=_result(202, '{"messages":[]}'))
    def test_email_omits_sign_in_links_and_tokens(self, mock_post, mock_webhook):
        from apps.actions.webhook_transport import WebhookPostResult

        mock_webhook.return_value = WebhookPostResult(status=200, excerpt='')
        sign_in = 'https://id.shellui.com/api/v1/magic-link/verify?token=example'
        payload = {
            **_failed_payload(),
            'magic_link_url': sign_in,
            'token': 'raw-secret',
            'raw_token': 'raw-secret',
            'access_token': 'jwt-example',
            'note': sign_in,
            'meta': {'refresh_token': 'refresh-example', 'display_name': 'My App'},
        }
        ActionRule.objects.create(
            company_id=self.company_id,
            name='Hook',
            event_type='hosting.deployment.failed',
            action_kind=ActionRule.ACTION_WEBHOOK,
            config={'url': 'https://example.com/hook', 'secret': 'plain-secret'},
        )
        with self.captureOnCommitCallbacks(execute=True):
            rows = emit_event(
                'hosting.deployment.failed',
                self.company_id,
                payload,
                actor={**self.actor, 'token': 'actor-token', 'magic_link_url': sign_in},
            )
        self.assertEqual(len(rows), 1)
        webhook = ActionOutbox.objects.get(delivery_kind=ActionOutbox.KIND_WEBHOOK)
        rendered_webhook = str(webhook.envelope)
        mock_webhook.assert_called_once()

        body = _posted_json(mock_post)
        rendered = str(body)
        self.assertEqual(body['payload']['display_name'], 'My App')
        self.assertEqual(body['payload']['error'], 'artifact_extract_failed')
        self.assertEqual(body['payload']['meta'], {'display_name': 'My App'})
        self.assertEqual(body['recipients'], [{'email': 'ada@acme.com', 'user_id': 7}])
        posted = mock_webhook.call_args.kwargs['body']
        logged = EventLog.objects.get()
        for secret in (sign_in, 'raw-secret', 'jwt-example', 'refresh-example', 'actor-token', 'token='):
            self.assertNotIn(secret, rendered)
            self.assertNotIn(secret, rendered_webhook)
            self.assertNotIn(secret.encode(), posted)
            self.assertNotIn(secret, str(logged.data))

    @patch('apps.actions.email_service.post_webhook_url', return_value=_result(202))
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
    @patch('apps.actions.email_service.post_webhook_url', return_value=_result(202))
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
        emailed = _posted_json(mock_email)
        self.assertEqual(emailed['recipients'], [{'email': 'ada@acme.com'}])
        self.assertNotIn('user_id', emailed['recipients'][0])

    @patch('apps.actions.email_service.post_webhook_url', return_value=_result(503, 'unavailable'))
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
        first_body = _posted_json(mock_post)

        mock_post.return_value = _result(202, '{"rule_enabled": true, "messages": []}')
        row.next_attempt_at = timezone.now()
        row.locked_until = None
        row.save(update_fields=['next_attempt_at', 'locked_until'])
        call_command('retry_webhooks', '--concurrency', '1')

        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)
        self.assertEqual(mock_post.call_count, 2)
        second_body = _posted_json(mock_post)
        self.assertEqual(first_body, second_body)
        self.assertEqual(first_body['idempotency_key'], second_body['idempotency_key'])

    @patch('apps.actions.email_service.post_webhook_url', return_value=_result(400, '{"error_code":"validation_failed"}'))
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

    @patch('apps.actions.email_service.post_webhook_url', return_value=_result(404, 'missing'))
    def test_not_found_is_retried_with_the_same_body(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event('hosting.app.deleted', self.company_id, {'display_name': 'My App'}, actor=self.actor)
        row = ActionOutbox.objects.get()
        self.assertEqual(row.status, ActionOutbox.STATUS_FAILED)
        first_body = _posted_json(mock_post)

        mock_post.return_value = _result(202, '{"rule_enabled": false, "skipped_reason": "rule_disabled", "messages": []}')
        row.next_attempt_at = timezone.now()
        row.locked_until = None
        row.save(update_fields=['next_attempt_at', 'locked_until'])
        call_command('retry_webhooks', '--concurrency', '1')

        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(_posted_json(mock_post), first_body)

    @patch(
        'apps.actions.email_service.post_webhook_url',
        return_value=_result(202, '{"rule_enabled": true, "skipped_reason": "no_recipients", "messages": []}'),
    )
    def test_empty_recipients_skip_is_finished(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event('hosting.deployment.failed', self.company_id, _failed_payload())
        row = ActionOutbox.objects.get()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)
        self.assertEqual(_posted_json(mock_post)['recipients'], [])
        call_command('retry_webhooks', '--concurrency', '1')
        self.assertEqual(mock_post.call_count, 1)

    def test_permanent_statuses_match_webhook_delivery(self):
        from apps.actions.email_service import email_status_is_permanent

        for code in (400, 401, 403, 405, 410, 413, 422):
            self.assertTrue(email_status_is_permanent(code), code)
        for code in (404, 408, 409, 425, 429, 402, 500, 502, 503):
            self.assertFalse(email_status_is_permanent(code), code)
        self.assertFalse(email_status_is_permanent(None))

    @patch('apps.actions.email_service.post_webhook_url')
    def test_api_key_is_not_logged_or_stored(self, mock_post):
        mock_post.side_effect = [
            OSError(f'connection failed token={API_KEY}'),
            _result(400, f'body mentions {API_KEY}'),
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
        with patch('apps.actions.email_service.post_webhook_url', return_value=_result(202)):
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
    @patch('apps.actions.email_service.post_webhook_url')
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
    @patch('apps.actions.email_service.post_webhook_url')
    def test_blank_api_key_is_unconfigured(self, mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            emit_event('hosting.app.created', 42, {'display_name': 'My App'})
        mock_post.assert_not_called()
        self.assertEqual(ActionOutbox.objects.count(), 0)


@override_settings(
    EMAIL_SERVICE_API_KEY='esk_test_hosting_key',
    ACTIONS_WEBHOOK_TIMEOUT_SECONDS=0.2,
)
class EmailServiceSsrfTests(TestCase):
    def test_private_and_link_local_urls_are_refused(self):
        for url in (
            'http://127.0.0.1:9',
            'http://10.1.2.3',
            'http://169.254.169.254',
            'http://[::1]:9',
        ):
            with self.subTest(url=url):
                with override_settings(EMAIL_SERVICE_URL=url, EMAIL_SERVICE_ALLOW_PRIVATE=False):
                    with self.assertRaises(EmailDeliveryError) as ctx:
                        post_email_event({'event_type': 'hosting.app.created', 'company_id': 1})
                self.assertTrue(ctx.exception.permanent)

    @override_settings(EMAIL_SERVICE_URL='http://127.0.0.1:9', EMAIL_SERVICE_ALLOW_PRIVATE=True)
    def test_private_url_connects_when_explicitly_allowed(self):
        with self.assertRaises(EmailDeliveryError) as ctx:
            post_email_event({'event_type': 'hosting.app.created', 'company_id': 1})
        self.assertFalse(ctx.exception.permanent)
        self.assertIn('failed', str(ctx.exception).lower())

