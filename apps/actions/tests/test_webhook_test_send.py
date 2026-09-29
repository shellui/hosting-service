import uuid
from unittest.mock import patch

from django.test import TestCase

from apps.actions.models import ActionRule
from apps.actions.webhook_test_send import send_webhook_test_for_rule


class WebhookTestSendSampleDataTests(TestCase):
    @patch('apps.actions.webhook_test_send.deliver_webhook_action')
    def test_consecutive_test_sends_use_distinct_uuids(self, mock_deliver):
        company_id = 10
        rule = ActionRule.objects.create(
            company_id=company_id,
            name='Hosting hook',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            enabled=True,
            config={'url': 'https://example.com/h', 'secret': 's'},
        )
        send_webhook_test_for_rule(rule=rule, company_id=company_id)
        first_envelope = mock_deliver.call_args.kwargs['envelope']
        send_webhook_test_for_rule(rule=rule, company_id=company_id)
        second_envelope = mock_deliver.call_args.kwargs['envelope']

        first_app_id = first_envelope['data']['app_id']
        second_app_id = second_envelope['data']['app_id']
        self.assertNotEqual(first_app_id, second_app_id)
        uuid.UUID(first_app_id)
        uuid.UUID(second_app_id)
        self.assertNotEqual(first_envelope['id'], second_envelope['id'])
