from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from apps.authapi.principal import HostingPrincipal


def require_staff_or_company_owner(request) -> tuple[HostingPrincipal | None, int | None, Response | None]:
    """
    Resolve company scope for Shellui Actions admin APIs.

    Staff may pass any ``company_id`` as a query parameter. Everyone else is scoped to the JWT
    ``company_id``; passing the same value is accepted, a different one is forbidden.
    """
    user = request.user
    if not user or not getattr(user, 'is_authenticated', False):
        return None, None, Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

    raw_token_company = getattr(user, 'company_id', None)
    token_company = int(raw_token_company) if raw_token_company is not None else None
    query_company = (request.GET.get('company_id') or '').strip()
    if query_company:
        try:
            company_id = int(query_company)
        except (TypeError, ValueError):
            return None, None, Response({'error': 'Invalid company_id parameter.'}, status=status.HTTP_400_BAD_REQUEST)
        if company_id != token_company and not getattr(user, 'is_staff', False):
            return None, None, Response(
                {'error': 'Requested company_id does not match token company_id.'},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif token_company is None:
        return None, None, Response(
            {'error': 'Missing company_id in access token.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    else:
        company_id = token_company

    if getattr(user, 'is_staff', False) or getattr(user, 'is_company_owner', False):
        return user, company_id, None
    return None, None, Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
