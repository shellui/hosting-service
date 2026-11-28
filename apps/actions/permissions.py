from rest_framework.permissions import SAFE_METHODS, BasePermission

# Same write modes as hosting: missing, read_only, and unknown values are read-only.
_AGENT_WRITE_ACCESS = frozenset({'full', 'ask'})


class ActionsAdminPermission(BasePermission):
    """
    Authenticated principals only; personal access tokens with ``pat_ro`` are read-only.

    Agent callers are not company owners. A missing ``mcp_access`` claim, or any
    value other than ``full`` or ``ask``, is read-only.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        claims = getattr(user, 'claims', None) or {}
        if claims.get('pat_ro') is True and request.method not in SAFE_METHODS:
            return False
        if getattr(user, 'agent_id', None):
            access = str(claims.get('mcp_access') or 'read_only').strip().lower() or 'read_only'
            if access not in _AGENT_WRITE_ACCESS and request.method not in SAFE_METHODS:
                return False
        return True
