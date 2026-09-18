"""Tests for company hosting access / waitlist API."""

from __future__ import annotations

from unittest.mock import patch

import jwt
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.hosting.models import AccessStatus, CompanyHostingAccess
from apps.hosting.services import HostingError, assert_hosting_access


def make_token(
    *,
    user_id: int = 1,
    company_id: int = 10,
    email: str = 'user@example.com',
    is_staff: bool = False,
    is_company_owner: bool = False,
    secret: str = 'test-secret',
) -> str:
    return jwt.encode(
        {
            'sub': str(user_id),
            'user_id': user_id,
            'company_id': company_id,
            'email': email,
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
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    HOSTING_DEBUG_OPEN=False,
)
class AccessViewStaffApprovalTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.jwks_patch = patch('apps.authapi.authentication.get_jwks_client')
        mock_client = self.jwks_patch.start()
        mock_client.return_value.get_signing_key.return_value = None
        self.addCleanup(self.jwks_patch.stop)
        CompanyHostingAccess.objects.create(
            company_id=10,
            status=AccessStatus.PENDING,
            requested_by_id=1,
        )

    def _auth(self, **kwargs):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(**kwargs)}'}

    def test_owner_cannot_self_approve(self):
        response = self.client.post(
            '/hosting/v1/access',
            {'status': AccessStatus.APPROVED},
            format='json',
            **self._auth(is_company_owner=True),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            CompanyHostingAccess.objects.get(company_id=10).status,
            AccessStatus.PENDING,
        )

    def test_owner_cannot_self_deny(self):
        response = self.client.post(
            '/hosting/v1/access',
            {'status': AccessStatus.DENIED},
            format='json',
            **self._auth(is_company_owner=True),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            CompanyHostingAccess.objects.get(company_id=10).status,
            AccessStatus.PENDING,
        )

    def test_staff_can_approve_company(self):
        response = self.client.post(
            '/hosting/v1/access',
            {'company_id': 10, 'status': AccessStatus.APPROVED, 'notes': 'ok'},
            format='json',
            **self._auth(is_staff=True, company_id=99),
        )
        self.assertEqual(response.status_code, 200)
        record = CompanyHostingAccess.objects.get(company_id=10)
        self.assertEqual(record.status, AccessStatus.APPROVED)
        self.assertEqual(record.notes, 'ok')

    def test_staff_can_deny_company(self):
        response = self.client.post(
            '/hosting/v1/access',
            {'company_id': 10, 'status': AccessStatus.DENIED},
            format='json',
            **self._auth(is_staff=True, company_id=99),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            CompanyHostingAccess.objects.get(company_id=10).status,
            AccessStatus.DENIED,
        )


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
)
class HostingDebugOpenSettingsTests(TestCase):
    def test_debug_without_explicit_env_is_fail_closed(self):
        with self.settings(DEBUG=True, HOSTING_DEBUG_OPEN=False):
            CompanyHostingAccess.objects.filter(company_id=10).delete()
            with self.assertRaises(HostingError) as ctx:
                assert_hosting_access(10)
            self.assertEqual(ctx.exception.code, 'hosting_access_denied')

    def test_prod_like_settings_do_not_bypass_waitlist(self):
        with self.settings(DEBUG=False, HOSTING_DEBUG_OPEN=False):
            CompanyHostingAccess.objects.filter(company_id=10).delete()
            with self.assertRaises(HostingError) as ctx:
                assert_hosting_access(10)
            self.assertEqual(ctx.exception.code, 'hosting_access_denied')

    def test_explicit_debug_open_bypasses_waitlist(self):
        with self.settings(DEBUG=False, HOSTING_DEBUG_OPEN=True):
            CompanyHostingAccess.objects.filter(company_id=10).delete()
            assert_hosting_access(10)
