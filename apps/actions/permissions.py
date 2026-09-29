from rest_framework.permissions import SAFE_METHODS, BasePermission


class ActionsAdminPermission(BasePermission):
    """
    Authenticated principals only; personal access tokens with ``pat_ro`` are read-only.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        claims = getattr(user, 'claims', None) or {}
        if claims.get('pat_ro') is True and request.method not in SAFE_METHODS:
            return False
        return True
