from rest_framework.permissions import BasePermission


class IsAuthenticatedPrincipal(BasePermission):
    """Require a HostingPrincipal from IdentityJWKSAuthentication."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and getattr(user, 'is_authenticated', False)):
            return False
        if getattr(user, 'deploy_token_id', None):
            # Deploy tokens only reach views that opt in, for the listed methods.
            return request.method in getattr(view, 'deploy_token_methods', ())
        return True


class IsStaffOrCompanyOwner(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return bool(getattr(user, 'is_staff', False) or getattr(user, 'is_company_owner', False))
