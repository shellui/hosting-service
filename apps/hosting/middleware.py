"""Host-aware routing for hosted app subdomains."""

from __future__ import annotations

from .hosts import slug_from_host


def apply_hosted_navigation_policy(response):
    """
    Default COOP for a hosted app is ``unsafe-none``.

    SecurityMiddleware otherwise sets ``same-origin``. Firefox then fails a
    top-level navigation from another site with ``NS_ERROR_DOM_COOP_FAILED``.
    ``same-origin-allow-popups`` still disagrees with that previous page.
    Do not set COEP or CORP. A COOP already on the response is kept.
    CSP, ``X-Content-Type-Options``, and HSTS are left untouched.
    """
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'unsafe-none')
    return response


def _set_cookie_has_domain(value: str) -> bool:
    parts = str(value).split(';')
    for part in parts[1:]:
        attr = part.split('=', 1)[0].strip().lower()
        if attr == 'domain':
            return True
    return False


def strip_parent_domain_cookies(response):
    """Remove Set-Cookie values that carry a Domain attribute.

    A Domain cookie set on ``{slug}.{HOSTING_APP_DOMAIN}`` is sent to every
    host under that parent, including identity and admin when they share it.
    Host-only cookies stay on the app hostname.
    """
    doomed = [key for key, morsel in response.cookies.items() if morsel['domain']]
    for key in doomed:
        del response.cookies[key]
    raw = response.headers.get('Set-Cookie')
    if raw and _set_cookie_has_domain(raw):
        del response['Set-Cookie']
    return response


class HostedAppCookieScopeMiddleware:
    """Drop parent-domain cookies on hosted app responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if slug_from_host(request.get_host()):
            strip_parent_domain_cookies(response)
        return response


class HostedAppNavigationPolicyMiddleware:
    """Apply the hosted-app COOP default before SecurityMiddleware's setdefault."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if slug_from_host(request.get_host()):
            apply_hosted_navigation_policy(response)
        return response


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
