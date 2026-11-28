"""Agent bearers stay off general REST, and refresh tokens are refused."""

from __future__ import annotations

from unittest.mock import patch

import jwt
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from apps.authapi.authentication import IdentityJWKSAuthentication
from apps.authapi.permissions import IsAuthenticatedPrincipal
from apps.authapi.principal import principal_from_claims


def _agent_claims(**extra):
    claims = {
        'sub': 'agent:agent-1',
        'agent_id': 'agent-1',
        'company_id': 10,
        'grant_version': 0,
        'owner_user_id': 7,
        'user_metadata': {'is_staff': True, 'is_company_owner': True},
        'exp': 2**31 - 1,
    }
    claims.update(extra)
    return claims


@override_settings(
    JWT_HS256_FALLBACK_SECRET='test-secret',
    ALLOW_JWT_HS256_FALLBACK=True,
    IDENTITY_JWKS_URL='http://jwks.test/.well-known/jwks.json',
    IDENTITY_AUDIENCE='',
    IDENTITY_ISSUER='',
    JWT_ALGORITHMS=['RS256'],
    DEBUG=True,
)
class AgentBearerScopeTests(SimpleTestCase):
    def setUp(self):
        self.auth = IdentityJWKSAuthentication()
        jwks = patch('apps.authapi.authentication.get_jwks_client').start()
        jwks.return_value.get_signing_key.return_value = None
        jwks.return_value.key_count.return_value = 0
        jwks.return_value.key_ids.return_value = []
        self.addCleanup(patch.stopall)

    def _token(self, claims: dict) -> str:
        return jwt.encode(claims, 'test-secret', algorithm='HS256')

    def _authenticate(self, method: str, path: str, claims: dict):
        raw = self._token(claims)
        django_request = getattr(RequestFactory(), method.lower())(
            path,
            HTTP_AUTHORIZATION=f'Bearer {raw}',
        )
        return self.auth.authenticate(Request(django_request))

    def test_agent_is_the_member_and_never_owner(self):
        principal = principal_from_claims(_agent_claims())
        self.assertEqual(principal.user_id, 7)
        self.assertEqual(principal.agent_id, 'agent-1')
        self.assertFalse(principal.is_company_owner)
        self.assertFalse(principal.is_staff)
        self.assertEqual(principal.claims['mcp_access'], 'read_only')

    def test_missing_mcp_access_is_read_only(self):
        principal = principal_from_claims(_agent_claims())
        self.assertEqual(principal.claims['mcp_access'], 'read_only')
        explicit = principal_from_claims(_agent_claims(mcp_access='full'))
        self.assertEqual(explicit.claims['mcp_access'], 'full')

        class _Request:
            def __init__(self, method, user):
                self.method = method
                self.user = user

        permission = IsAuthenticatedPrincipal()
        self.assertFalse(permission.has_permission(_Request('PUT', principal), None))
        self.assertTrue(permission.has_permission(_Request('GET', principal), None))
        self.assertTrue(permission.has_permission(_Request('PUT', explicit), None))

    def test_rest_refuses_agent_bearer(self):
        with self.assertRaises(AuthenticationFailed) as ctx:
            self._authenticate('get', '/hosting/v1/apps', _agent_claims(mcp_access='full'))
        self.assertIn('not accepted on this route', str(ctx.exception.detail))

    def test_post_mcp_accepts_agent_bearer(self):
        principal, _auth = self._authenticate('post', '/mcp', _agent_claims(mcp_access='full'))
        self.assertEqual(principal.agent_id, 'agent-1')
        self.assertFalse(principal.is_company_owner)
        self.assertEqual(principal.user_id, 7)

    def test_artifact_upload_accepts_agent_bearer(self):
        principal, _auth = self._authenticate(
            'put',
            '/hosting/v1/apps/demo/deployments/11111111-1111-1111-1111-111111111111/upload',
            _agent_claims(mcp_access='full'),
        )
        self.assertEqual(principal.agent_id, 'agent-1')
        self.assertFalse(principal.is_company_owner)

    def test_refresh_token_is_refused_as_bearer(self):
        claims = {
            'sub': '1',
            'user_id': 1,
            'company_id': 10,
            'token_type': 'refresh',
            'user_metadata': {'is_staff': False, 'is_company_owner': True},
            'exp': 2**31 - 1,
        }
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate_credentials(self._token(claims))
        self.assertIn('refresh', str(ctx.exception.detail).lower())

    def test_agent_refresh_token_is_refused_on_mcp(self):
        claims = _agent_claims(token_type='refresh', mcp_access='full')
        with self.assertRaises(AuthenticationFailed):
            self._authenticate('post', '/mcp', claims)
