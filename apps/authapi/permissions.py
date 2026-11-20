from rest_framework.permissions import SAFE_METHODS, BasePermission

# Write modes Identity puts on an agent access token. Anything else, including
# a missing claim, is read-only.
_AGENT_WRITE_ACCESS = frozenset({'full', 'ask'})


def _agent_mcp_access(user) -> str | None:
    """Return the agent access mode, or None when this caller is not an agent."""
    if not getattr(user, 'agent_id', None):
        return None
    claims = getattr(user, 'claims', None) or {}
    access = str(claims.get('mcp_access') or 'read_only').strip().lower()
    return access or 'read_only'


class IsAuthenticatedPrincipal(BasePermission):
    """Require a HostingPrincipal from IdentityJWKSAuthentication."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and getattr(user, 'is_authenticated', False)):
            return False
        if getattr(user, 'deploy_token_id', None):
            # Deploy tokens only reach views that opt in, for the listed methods.
            return request.method in getattr(view, 'deploy_token_methods', ())
        agent_access = _agent_mcp_access(user)
        if agent_access is not None:
            if agent_access not in _AGENT_WRITE_ACCESS and request.method not in SAFE_METHODS:
                return False
            return True
        auth = getattr(request, 'auth', None)
        if isinstance(auth, dict):
            mcp_access = auth.get('mcp_access')
        else:
            mcp_access = (getattr(user, 'claims', None) or {}).get('mcp_access')
        if mcp_access == 'read_only' and request.method not in SAFE_METHODS:
            return False
        return True


class IsStaffOrCompanyOwner(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if getattr(user, 'is_staff', False) or getattr(user, 'is_company_owner', False):
            return True
        # Agents are not company owners. POST /mcp dispatches them onto these
        # views with the company on the token. Direct REST never authenticates
        # an agent token onto this permission.
        return bool(getattr(user, 'agent_id', None) and getattr(user, 'company_id', None) is not None)
