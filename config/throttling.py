"""DRF throttling for abuse-prone hosting endpoints."""

from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache
from rest_framework.throttling import SimpleRateThrottle

from config.client_ip import get_client_ip


def _limits_for_scope(scope: str) -> tuple[int, int]:
    spec = getattr(settings, 'HOSTING_RATE_LIMITS', {}).get(scope) or {'limit': 60, 'window': 60}
    return int(spec['limit']), int(spec['window'])


class HostingScopeThrottle(SimpleRateThrottle):
    """
    Per-view scope via ``rate_limit_scope`` on the APIView.

    Buckets by authenticated ``user_id``, else client IP.
    """

    rate = '1/s'  # placeholder; ``allow_request`` reads HOSTING_RATE_LIMITS per scope
    cache_format = 'hosting_throttle_%(scope)s_%(ident)s'

    def get_rate(self):
        return self.rate

    def get_cache_key(self, request, view):
        if not getattr(settings, 'HOSTING_RATE_LIMIT_ENABLED', True):
            return None
        scope = getattr(view, 'rate_limit_scope', None)
        if not scope:
            return None
        user = request.user
        if user and getattr(user, 'is_authenticated', False):
            ident = f'user_{getattr(user, "user_id", user.pk)}'
        else:
            ident = f'ip_{get_client_ip(request) or "unknown"}'
        return self.cache_format % {'scope': scope, 'ident': ident}

    def allow_request(self, request, view):
        if not getattr(settings, 'HOSTING_RATE_LIMIT_ENABLED', True):
            return True
        scope = getattr(view, 'rate_limit_scope', 'default')
        self.num_requests, self.duration = _limits_for_scope(scope)
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        if len(self.history) >= self.num_requests:
            return self.throttle_failure()
        return self.throttle_success()

    def timer(self):
        return time.time()
