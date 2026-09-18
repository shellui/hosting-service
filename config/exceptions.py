"""DRF exception handler: attach request_id and log server errors."""

from __future__ import annotations

import logging

from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    request = context.get('request')
    request_id = getattr(request, 'request_id', None) if request is not None else None
    if isinstance(exc, Throttled) and isinstance(response.data, dict):
        response.data = {
            'statusCode': '429',
            'error': 'rate_limited',
            'message': 'Too many requests. Please try again later.',
            **({'request_id': request_id} if request_id else {}),
        }

    if request_id and isinstance(response.data, dict):
        response.data.setdefault('request_id', request_id)

    if response.status_code >= 500:
        method = getattr(request, 'method', '?')
        path = getattr(request, 'path', '?')
        logger.error(
            '%s %s failed with %s (%s): %s',
            method,
            path,
            response.status_code,
            type(exc).__name__,
            exc,
        )
    return response
