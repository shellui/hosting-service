"""Startup checks for hosted-app cookie scope."""

from django.core.checks import Warning, register

from apps.hosting.domain_scope import shared_parent_service_urls


@register(tags='security')
def warn_shared_hosting_parent_domain(app_configs, **kwargs):
    """Warn when hosted apps and a platform URL share a registrable domain."""
    matches = shared_parent_service_urls()
    if not matches:
        return []
    parent = matches[0][2]
    listed = ', '.join(f'{name} ({url})' for name, url, _parent in matches)
    return [
        Warning(
            f'HOSTING_APP_DOMAIN shares the parent domain {parent} with {listed}.',
            hint=(
                'Use a separate registrable domain for hosted apps and for identity '
                'and admin. For example, serve apps on shellui.app and keep identity '
                'and admin on shellui.com. A page on an app host can set a cookie '
                'with that parent Domain, and the browser will send it to those services.'
            ),
            id='hosting.W001',
        )
    ]
