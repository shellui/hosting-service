"""Client IP resolution for rate limiting and logging (honors trusted reverse proxies)."""

from __future__ import annotations

import ipaddress

from django.conf import settings
from django.http import HttpRequest


def _parse_ip_hop(hop: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Strip ports or brackets from an X-Forwarded-For hop; return None if not a valid IP."""
    raw = hop.strip()
    if not raw:
        return None
    if raw.startswith('['):
        end = raw.find(']')
        if end == -1:
            return None
        candidate = raw[1:end].strip()
    elif raw.count(':') == 1 and '.' in raw:
        candidate, _, _port = raw.partition(':')
        candidate = candidate.strip()
    else:
        candidate = raw
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _addr_for_trusted_match(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _ip_in_trusted_proxies(ip: str, trusted: tuple[str, ...]) -> bool:
    parsed = _parse_ip_hop(ip)
    if parsed is None:
        return False
    addr = _addr_for_trusted_match(parsed)
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


def _xff_hops(xff: str) -> list[str]:
    return [part.strip() for part in xff.split(',') if part.strip()]


def _client_ip_from_xff(xff: str, trusted: tuple[str, ...]) -> str | None:
    """
    Walk ``X-Forwarded-For`` from the right (closest to this server).

    Skip hops listed in ``trusted``; return the first untrusted address (the client).
    Invalid hops are skipped. Hops may include IPv4 ports or bracketed IPv6.
    """
    hops = _xff_hops(xff)
    if not hops:
        return None
    for hop in reversed(hops):
        parsed = _parse_ip_hop(hop)
        if parsed is None:
            continue
        if _ip_in_trusted_proxies(hop, trusted):
            continue
        return str(parsed)
    return None


def client_ip_rate_limit_key(ip: str | None) -> str:
    """
    Stable rate-limit bucket for a client IP.

    IPv6 addresses are grouped by /64 prefix so a single subnet cannot exhaust
    distinct buckets. Audit logging should use the full address from ``get_client_ip``.
    """
    if not ip or not str(ip).strip():
        return 'unknown'
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return str(ip).strip()
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv6Address):
        prefix = ipaddress.IPv6Network(f'{addr}/64', strict=False)
        return f'{prefix.network_address}/64'
    return str(addr)


def get_client_ip(request: HttpRequest) -> str | None:
    """
    Best-effort client IP for audit and rate limiting.

    When ``REMOTE_ADDR`` is listed in ``settings.TRUSTED_PROXY_IPS``, parse
    ``X-Forwarded-For`` from the right and use the first hop that is not a trusted
    proxy (supports comma-separated chains and CIDR entries in ``TRUSTED_PROXY_IPS``).
    Otherwise return ``REMOTE_ADDR`` so clients cannot spoof audit IPs by sending
    ``X-Forwarded-For`` directly to the app.
    """
    remote = request.META.get('REMOTE_ADDR')
    remote_parsed = _parse_ip_hop(remote) if isinstance(remote, str) else None
    remote_addr = str(remote_parsed) if remote_parsed is not None else None
    if remote_addr is None and isinstance(remote, str) and remote.strip():
        remote_addr = remote.strip()
    trusted = tuple(getattr(settings, 'TRUSTED_PROXY_IPS', ()) or ())
    if remote_addr and trusted and _ip_in_trusted_proxies(remote_addr, trusted):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if isinstance(xff, str) and xff.strip():
            from_xff = _client_ip_from_xff(xff.strip(), trusted)
            if from_xff:
                return from_xff
    if remote_addr:
        return remote_addr
    return None
