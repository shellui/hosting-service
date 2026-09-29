from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from apps.authapi.principal import HostingPrincipal


def require_staff_or_company_owner(request) -> tuple[HostingPrincipal | None, int | None, Response | None]:
    """
    Resolve company scope for Shellui Actions admin APIs.

    Staff may pass ``company_id`` as a query parameter. Everyone else uses ``company_id`` from the JWT only.
    """
    user = request.user
    if not user or not getattr(user, 'is_authenticated', False):
        return None, None, Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

    query_company = (request.GET.get('company_id') or '').strip()
    if query_company and not getattr(user, 'is_staff', False):
        return None, None, Response(
            {
                'error': (
                    'Remove company_id from the query string; '
                    'company scope comes from the access token only.'
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if query_company and getattr(user, 'is_staff', False):
        try:
            company_id = int(query_company)
        except (TypeError, ValueError):
            return None, None, Response({'error': 'Invalid company_id parameter.'}, status=status.HTTP_400_BAD_REQUEST)
    else:
        raw = getattr(user, 'company_id', None)
        if raw is None:
            return None, None, Response(
                {'error': 'Missing company_id in access token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        company_id = int(raw)

    if getattr(user, 'is_staff', False) or getattr(user, 'is_company_owner', False):
        return user, company_id, None
    return None, None, Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
