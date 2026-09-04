"""Host-aware routing for hosted app subdomains."""

from __future__ import annotations

from .hosts import slug_from_host


class HostedAppServeMiddleware:
    """
    Serve the hosted site for every path on app subdomains.

    Platform routes (Django admin, API, docs, apex landing) apply only when the
    Host is not a hosted-app subdomain — e.g. ``shellui.app`` / ``localhost``.
    Without this, a SPA refresh on ``{slug}.*/admin`` would hit Django admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not slug_from_host(request.get_host()):
            return self.get_response(request)

        from .serve import AppServeView

        path = request.path_info.lstrip('/')
        return AppServeView.as_view()(request, path=path)
