"""Client IP resolution for rate limiting (honors trusted reverse proxies)."""

from __future__ import annotations

import ipaddress

from django.conf import settings
from django.http import HttpRequest


def _ip_in_trusted_proxies(ip: str, trusted: tuple[str, ...]) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    for entry in trusted:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if '/' in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: HttpRequest) -> str | None:
    """
    Best-effort client IP for rate limiting.

    ``X-Forwarded-For`` is used only when ``REMOTE_ADDR`` is listed in
    ``settings.TRUSTED_PROXY_IPS``. Otherwise ``REMOTE_ADDR`` is returned so
    clients cannot spoof IPs by sending XFF headers directly.
    """
    remote = request.META.get('REMOTE_ADDR')
    remote_addr = remote.strip() if isinstance(remote, str) and remote.strip() else None
    trusted = tuple(getattr(settings, 'TRUSTED_PROXY_IPS', ()) or ())
    if remote_addr and trusted and _ip_in_trusted_proxies(remote_addr, trusted):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if isinstance(xff, str) and xff.strip():
            return xff.split(',')[0].strip()
    if remote_addr:
        return remote_addr
    return None
