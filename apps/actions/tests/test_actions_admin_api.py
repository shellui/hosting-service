from unittest.mock import patch

import jwt
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.actions.models import ActionOutbox, ActionRule


def make_token(
    *,
    user_id: int = 1,
    company_id: int = 10,
    is_staff: bool = False,
    is_company_owner: bool = True,
    secret: str = 'test-secret',
) -> str:
    return jwt.encode(
        {
            'sub': str(user_id),
            'user_id': user_id,
            'company_id': company_id,
            'email': 'owner@acme.test',
            'user_metadata': {
                'is_staff': is_staff,
                'is_company_owner': is_company_owner,
            },
            'exp': 2**31 - 1,
        },
        secret,
        algorithm='HS256',
    )


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
)
class ActionsAdminApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company_id = 10
        self.jwks_patch = patch('apps.authapi.authentication.get_jwks_client')
        mock_client = self.jwks_patch.start()
        mock_client.return_value.get_signing_key.return_value = None
        self.addCleanup(self.jwks_patch.stop)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {make_token(company_id=self.company_id)}')

    def test_events_catalog_payload_fields(self):
        response = self.client.get('/api/v1/actions/events')
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data['results'] if r['type'] == 'hosting.app.created')
        self.assertIn('payload_fields', row)
        self.assertIn('sample_envelope', row)
        self.assertEqual(row['supported_action_kinds'], ['webhook'])

    def test_create_webhook_rule_returns_secret_once(self):
        response = self.client.post(
            '/api/v1/actions/rules',
            {
                'name': 'n8n',
                'event_type': 'hosting.app.created',
                'url': 'https://hooks.example.com/app',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['action_kind'], 'webhook')
        self.assertTrue(response.data['secret'].startswith('whsec_'))
        self.assertTrue(response.data['config']['has_secret'])
        self.assertNotIn('secret', response.data['config'])

        listed = self.client.get('/api/v1/actions/rules')
        self.assertNotIn('secret', listed.data['results'][0])
        self.assertTrue(listed.data['results'][0]['config']['has_secret'])

    def test_rotate_secret_returns_new_secret_once(self):
        create = self.client.post(
            '/api/v1/actions/rules',
            {
                'name': 'Hook',
                'event_type': 'hosting.app.created',
                'url': 'https://hooks.example.com/app',
            },
            format='json',
        )
        rule_id = create.data['id']
        first_secret = create.data['secret']
        rotate = self.client.post(f'/api/v1/actions/rules/{rule_id}/rotate-secret')
        self.assertEqual(rotate.status_code, 200)
        self.assertTrue(rotate.data['secret'].startswith('whsec_'))
        self.assertNotEqual(rotate.data['secret'], first_secret)
        self.assertNotIn('secret', rotate.data.get('config', {}))

    def test_list_deliveries_and_requeue(self):
        rule = ActionRule.objects.create(
            company_id=self.company_id,
            name='Hook',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            config={'url': 'https://example.com/h', 'secret': 's'},
        )
        row = ActionOutbox.objects.create(
            company_id=self.company_id,
            action_rule=rule,
            event_type='hosting.app.created',
            envelope={'id': '1', 'type': 'hosting.app.created', 'data': {}},
            status=ActionOutbox.STATUS_DEAD,
            last_error='fail',
        )
        listed = self.client.get('/api/v1/actions/deliveries')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data['count'], 1)

        detail = self.client.get(f'/api/v1/actions/deliveries/{row.pk}')
        self.assertEqual(detail.status_code, 200)
        self.assertIn('attempts', detail.data)

        requeue = self.client.post(f'/api/v1/actions/deliveries/{row.pk}/requeue')
        self.assertEqual(requeue.status_code, 200)
        self.assertEqual(requeue.data['status'], 'pending')

    @patch('apps.actions.webhook_test_send.deliver_webhook_action')
    def test_send_test_webhook(self, mock_deliver):
        rule = ActionRule.objects.create(
            company_id=self.company_id,
            name='Hook',
            event_type='hosting.app.created',
            action_kind=ActionRule.ACTION_WEBHOOK,
            enabled=True,
            config={'url': 'https://example.com/h', 'secret': 's'},
        )
        response = self.client.post(f'/api/v1/actions/rules/{rule.pk}/send-test')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        mock_deliver.assert_called_once()
