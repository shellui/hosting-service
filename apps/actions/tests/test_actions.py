import json
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.actions.delivery import backoff_seconds, claim_next_pending_outbox, deliver_outbox_row
from apps.actions.emit import emit_event
from apps.actions.handlers.webhook import WebhookDeliveryError
from apps.actions.models import ActionOutbox, ActionRule, DeliveryAttempt
from apps.actions.ssrf import SSRFError, validate_webhook_url
from apps.actions.webhook_retry import compute_retry_delay_seconds, is_permanent_http_status
from apps.actions.webhook_signing import (
    encode_webhook_envelope,
    generate_webhook_signing_secret,
    normalize_webhook_signing_secret,
    sign_webhook_body,
)
from apps.actions.webhook_transport import WebhookPostResult


def _post_result(status: int, excerpt: str = '', retry_after: int | None = None) -> WebhookPostResult:
    return WebhookPostResult(status=status, excerpt=excerpt, retry_after_seconds=retry_after)


@override_settings(ACTIONS_WEBHOOK_SYNC_DELIVERY=True)
class EmitEventTests(TestCase):
    def setUp(self):
        self.company_a = 100
        self.company_b = 200
        ActionRule.objects.create(
            company_id=self.company_a,
            name='Hook',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            config={'url': 'https://example.com/hook', 'secret': 'plain-secret'},
        )

    def test_unknown_event_type_raises(self):
        with self.assertRaises(ValueError):
            emit_event('not.real', self.company_a, {})

    def test_no_rules_returns_empty(self):
        rows = emit_event(
            'hosting.app.created',
            self.company_b,
            {'app_id': 'x'},
        )
        self.assertEqual(rows, [])
        self.assertEqual(ActionOutbox.objects.count(), 0)

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(200))
    def test_emit_creates_outbox_and_delivers_on_commit(self, _mock_post):
        with self.captureOnCommitCallbacks(execute=True):
            rows = emit_event(
                'hosting.app.created',
                self.company_a,
                {'app_id': '550e8400-e29b-41d4-a716-446655440000', 'name': 'demo'},
            )
        self.assertEqual(len(rows), 1)
        row = ActionOutbox.objects.get(pk=rows[0].pk)
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)

    def test_company_isolation(self):
        emit_event('hosting.app.created', self.company_b, {'app_id': 'x'})
        self.assertEqual(ActionOutbox.objects.count(), 0)


class WebhookHandlerTests(TestCase):
    def setUp(self):
        self.company_id = 42
        self.rule = ActionRule.objects.create(
            company_id=self.company_id,
            name='n8n',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            enabled=True,
            config={
                'url': 'https://example.com/hook',
                'secret': 'plain-secret',
            },
        )

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(200))
    def test_webhook_posts_signed_json(self, mock_post):
        envelope = {
            'id': 'evt-1',
            'type': 'hosting.app.created',
            'time': '2026-01-01T00:00:00+00:00',
            'company': {'id': self.company_id},
            'data': {'app_id': '1'},
        }
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type=envelope['type'],
            envelope=envelope,
        )
        deliver_outbox_row(row.pk)
        mock_post.assert_called_once()
        _args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['body'], encode_webhook_envelope(envelope))
        headers = kwargs['headers']
        self.assertIn('webhook-signature', headers)
        self.assertIn('webhook-id', headers)
        self.assertEqual(headers['webhook-id'], 'evt-1')
        self.assertEqual(headers['X-Shellui-Event'], 'hosting.app.created')
        self.assertEqual(headers['X-Shellui-Delivery-Attempt'], '1')
        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(200))
    def test_unicode_payload_and_whsec_secret(self, mock_post):
        secret = generate_webhook_signing_secret()
        self.rule.config = {'url': 'https://example.com/hook', 'secret': secret}
        self.rule.save()
        envelope = {
            'id': 'evt-unicode',
            'type': 'hosting.app.created',
            'time': '2026-01-01T00:00:00+00:00',
            'company': {'id': self.company_id},
            'data': {'display_name': 'Café Shellui'},
        }
        body = encode_webhook_envelope(envelope)
        self.assertIn('Café'.encode('utf-8'), body)
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type=envelope['type'],
            envelope=envelope,
        )
        deliver_outbox_row(row.pk)
        headers = mock_post.call_args.kwargs['headers']
        expected_sig = sign_webhook_body(secret=secret, body=body, webhook_id='evt-unicode')
        self.assertEqual(headers['webhook-signature'], expected_sig['webhook-signature'])
        self.assertEqual(mock_post.call_args.kwargs['body'], body)

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(500, 'err'))
    def test_webhook_failure_records_attempt(self, mock_post):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': 'x', 'type': 'hosting.app.created', 'data': {}},
        )
        deliver_outbox_row(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_FAILED)
        self.assertIsNotNone(row.next_attempt_at)
        attempt = DeliveryAttempt.objects.get(outbox=row)
        self.assertEqual(attempt.http_status, 500)
        self.assertIn('HTTP 500', attempt.error_message)

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(404, 'missing'))
    def test_404_is_retryable_for_n8n(self, _mock_post):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': 'x', 'type': 'hosting.app.created', 'data': {}},
        )
        deliver_outbox_row(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_FAILED)
        self.assertIsNotNone(row.next_attempt_at)

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(403, 'forbidden'))
    def test_permanent_403_goes_dead(self, _mock_post):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': 'x', 'type': 'hosting.app.created', 'data': {}},
        )
        deliver_outbox_row(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DEAD)
        self.assertIsNone(row.next_attempt_at)

    @patch(
        'apps.actions.handlers.webhook.post_webhook_url',
        return_value=_post_result(429, 'rate limited', 120),
    )
    def test_retry_after_on_429(self, _mock_post):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': 'x', 'type': 'hosting.app.created', 'data': {}},
        )
        deliver_outbox_row(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_FAILED)
        delay = (row.next_attempt_at - timezone.now()).total_seconds()
        self.assertGreaterEqual(delay, 115)
        self.assertLessEqual(delay, 125)

    def test_ssrf_blocks_private_ip(self):
        with self.assertRaises(SSRFError):
            validate_webhook_url('http://127.0.0.1/hook')
        with self.assertRaises(WebhookDeliveryError):
            from apps.actions.handlers.webhook import deliver_webhook_action

            deliver_webhook_action(
                config={'url': 'http://127.0.0.1/hook', 'secret': 'x'},
                envelope={'id': '1', 'type': 't', 'data': {}},
            )


class BackoffTests(TestCase):
    def test_backoff_sequence(self):
        self.assertEqual(backoff_seconds(1), 30)
        self.assertEqual(backoff_seconds(2), 60)
        self.assertEqual(backoff_seconds(3), 120)
        self.assertEqual(backoff_seconds(10), 3600)


@override_settings(ACTIONS_OUTBOX_MAX_ATTEMPTS=3)
class RetryDeliveryTests(TestCase):
    def setUp(self):
        self.company_id = 7
        self.rule = ActionRule.objects.create(
            company_id=self.company_id,
            name='hook',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            config={'url': 'https://example.com/h', 'secret': 's'},
        )

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(500))
    def test_dead_after_max_attempts(self, _mock):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': '1', 'type': 'hosting.app.created', 'data': {}},
        )
        for _ in range(3):
            deliver_outbox_row(row.pk)
            row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_DEAD)


class RetryCommandTests(TestCase):
    def setUp(self):
        self.company_id = 9
        self.rule = ActionRule.objects.create(
            company_id=self.company_id,
            name='hook',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            config={'url': 'https://example.com/h', 'secret': 's'},
        )

    @patch('apps.actions.handlers.webhook.post_webhook_url', return_value=_post_result(200))
    def test_retry_command_processes_batch(self, _mock):
        ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': '1', 'type': 'hosting.app.created', 'data': {}},
            status=ActionOutbox.STATUS_FAILED,
            next_attempt_at=timezone.now(),
        )
        call_command('retry_webhooks', batch_size=10, max_seconds=5, concurrency=1)
        row = ActionOutbox.objects.get()
        self.assertEqual(row.status, ActionOutbox.STATUS_DELIVERED)

    def test_dry_run_claims_without_http(self):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': '1', 'type': 'hosting.app.created', 'data': {}},
            status=ActionOutbox.STATUS_PENDING,
        )
        with patch('apps.actions.delivery.deliver_outbox_row') as mock_deliver:
            call_command('retry_webhooks', batch_size=5, dry_run=True)
            mock_deliver.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, ActionOutbox.STATUS_PENDING)

    def test_skip_locked_claim(self):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': '1', 'type': 'hosting.app.created', 'data': {}},
            status=ActionOutbox.STATUS_FAILED,
            next_attempt_at=timezone.now(),
            locked_until=timezone.now() + timedelta(minutes=5),
        )
        claimed = claim_next_pending_outbox()
        self.assertIsNone(claimed)
        row.refresh_from_db()
        self.assertIsNotNone(row.locked_until)

    def test_stale_lease_reclaimed(self):
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=self.rule,
            event_type='hosting.app.created',
            envelope={'id': '1', 'type': 'hosting.app.created', 'data': {}},
            status=ActionOutbox.STATUS_FAILED,
            next_attempt_at=timezone.now(),
            locked_until=timezone.now() - timedelta(seconds=30),
        )
        claimed = claim_next_pending_outbox()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, row.pk)


class NullableActionRuleLockTests(TestCase):
    """Email rows have no action rule. Postgres rejects FOR UPDATE on that outer join."""

    def _assert_locks_outbox_only(self, queries, *, skip_locked):
        if connection.vendor != 'postgresql':
            return
        locked = [query['sql'] for query in queries if 'FOR UPDATE' in query['sql']]
        joined = [sql for sql in locked if 'JOIN' in sql]
        self.assertEqual(len(joined), 1, locked)
        sql = joined[0]
        outbox = connection.ops.quote_name(ActionOutbox._meta.db_table)
        rule = connection.ops.quote_name(ActionRule._meta.db_table)
        self.assertIn(f'FOR UPDATE OF {outbox}', sql)
        self.assertNotIn(rule, sql.split('FOR UPDATE', 1)[1])
        if skip_locked:
            self.assertIn('SKIP LOCKED', sql)
        else:
            self.assertNotIn('SKIP LOCKED', sql)

    def test_claim_and_deliver_email_row_without_action_rule(self):
        row = ActionOutbox.objects.create(
            company_id=3,
            delivery_kind=ActionOutbox.KIND_EMAIL,
            event_type='hosting.deployment.failed',
            envelope={'id': 'email-1', 'type': 'hosting.deployment.failed', 'data': {}},
            status=ActionOutbox.STATUS_PENDING,
        )
        with CaptureQueriesContext(connection) as claimed_queries:
            claimed = claim_next_pending_outbox()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, row.pk)
        self.assertIsNone(claimed.action_rule_id)
        self.assertIsNotNone(claimed.locked_until)
        self._assert_locks_outbox_only(claimed_queries.captured_queries, skip_locked=True)

        with patch('apps.actions.delivery.post_email_event', return_value=202) as post_email:
            with CaptureQueriesContext(connection) as delivered_queries:
                delivered = deliver_outbox_row(row.pk)
        post_email.assert_called_once()
        self.assertEqual(delivered.status, ActionOutbox.STATUS_DELIVERED)
        self.assertIsNone(delivered.locked_until)
        self._assert_locks_outbox_only(delivered_queries.captured_queries, skip_locked=False)


class WebhookSigningTests(TestCase):
    def test_signature_format(self):
        body = b'{"ok":true}'
        headers = sign_webhook_body(secret='secret', body=body, webhook_id='id-1')
        self.assertTrue(headers['webhook-signature'].startswith('v1,'))

    def test_whsec_decodes_base64_key(self):
        secret = generate_webhook_signing_secret()
        self.assertTrue(secret.startswith('whsec_'))
        key = normalize_webhook_signing_secret(secret)
        self.assertEqual(len(key), 32)


class WebhookRetryPolicyTests(TestCase):
    def test_permanent_statuses(self):
        for code in (400, 401, 403, 405, 410, 413, 422):
            self.assertTrue(is_permanent_http_status(code), code)
        for code in (404, 408, 409, 425, 429, 500, 503):
            self.assertFalse(is_permanent_http_status(code), code)

    def test_retry_after_uses_max_of_backoff_and_header(self):
        delay = compute_retry_delay_seconds(
            attempt_number=1,
            http_status=503,
            retry_after_seconds=90,
            base_backoff_seconds=backoff_seconds(1),
        )
        self.assertEqual(delay, 90)
        short_header = compute_retry_delay_seconds(
            attempt_number=1,
            http_status=429,
            retry_after_seconds=10,
            base_backoff_seconds=backoff_seconds(1),
        )
        self.assertEqual(short_header, 30)
        capped = compute_retry_delay_seconds(
            attempt_number=1,
            http_status=429,
            retry_after_seconds=99999,
            base_backoff_seconds=backoff_seconds(1),
        )
        self.assertEqual(capped, 3600)
