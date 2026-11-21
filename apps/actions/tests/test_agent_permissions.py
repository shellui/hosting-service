"""Agent callers on Shellui Actions are not company owners."""

from django.test import RequestFactory, SimpleTestCase
from rest_framework.request import Request

from apps.actions.admin_scope import require_staff_or_company_owner
from apps.actions.permissions import ActionsAdminPermission
from apps.authapi.principal import HostingPrincipal, principal_from_claims


def _agent(**extra):
    claims = {
        'sub': 'agent:agent-1',
        'agent_id': 'agent-1',
        'company_id': 10,
        'grant_version': 0,
        'owner_user_id': 4,
    }
    claims.update(extra)
    return principal_from_claims(claims)


class _Request:
    def __init__(self, method, user):
        self.method = method
        self.user = user


class ActionsAgentPermissionTests(SimpleTestCase):
    def test_missing_mcp_access_is_read_only(self):
        user = _agent()
        self.assertEqual(user.claims['mcp_access'], 'read_only')
        self.assertFalse(user.is_company_owner)
        permission = ActionsAdminPermission()
        self.assertFalse(permission.has_permission(_Request('POST', user), None))
        self.assertTrue(permission.has_permission(_Request('GET', user), None))

    def test_full_access_may_write(self):
        user = _agent(mcp_access='full')
        self.assertTrue(ActionsAdminPermission().has_permission(_Request('POST', user), None))

    def test_unknown_mcp_access_is_read_only(self):
        user = _agent(mcp_access='admin')
        self.assertFalse(ActionsAdminPermission().has_permission(_Request('POST', user), None))

    def test_agent_company_scope_is_not_owner(self):
        user = _agent(mcp_access='full')
        request = Request(RequestFactory().get('/api/v1/actions/rules'))
        request.user = user
        actor, company_id, err = require_staff_or_company_owner(request)
        self.assertIsNone(err)
        self.assertIs(actor, user)
        self.assertEqual(company_id, 10)
        self.assertFalse(user.is_company_owner)

        other = Request(RequestFactory().get('/api/v1/actions/rules', {'company_id': '11'}))
        other.user = user
        _actor, _company, err = require_staff_or_company_owner(other)
        self.assertEqual(err.status_code, 403)

    def test_member_without_owner_flag_stays_forbidden(self):
        user = HostingPrincipal(user_id=4, company_id=10, is_company_owner=False)
        request = Request(RequestFactory().get('/api/v1/actions/rules'))
        request.user = user
        _actor, _company, err = require_staff_or_company_owner(request)
        self.assertEqual(err.status_code, 403)
