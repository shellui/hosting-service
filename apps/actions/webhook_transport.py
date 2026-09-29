"""HTTP(S) POST to a pre-resolved webhook endpoint (SSRF-safe connect)."""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection, HTTPResponse

from apps.actions.ssrf import ResolvedWebhookEndpoint, SSRFError, resolve_webhook_endpoint
from apps.actions.webhook_retry import parse_retry_after_header

_RESPONSE_EXCERPT_MAX = 512


class WebhookHTTPError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        response_excerpt: str = '',
        retry_after_seconds: int | None = None,
        permanent: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.response_excerpt = response_excerpt
        self.retry_after_seconds = retry_after_seconds
        self.permanent = permanent


@dataclass(frozen=True)
class WebhookPostResult:
    status: int
    excerpt: str
    retry_after_seconds: int | None = None


class PinnedHTTPSConnection(HTTPSConnection):
    """
    Connect to a pinned IP (SSRF-safe) while verifying TLS for the original hostname (SNI).
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float,
        context: ssl.SSLContext,
        connect_host: str,
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._pinned_connect_host = connect_host

    def connect(self) -> None:
        address = (self._pinned_connect_host, self.port)
        self.sock = socket.create_connection(address, self.timeout, self.source_address)
        if self._context is not None:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _read_response_excerpt(response: HTTPResponse) -> str:
    try:
        raw = response.read(_RESPONSE_EXCERPT_MAX + 1)
    except OSError:
        return ''
    if not raw:
        return ''
    text = raw[:_RESPONSE_EXCERPT_MAX].decode('utf-8', errors='replace')
    if len(raw) > _RESPONSE_EXCERPT_MAX:
        text = f'{text}…'
    return text.strip()


def _tls_server_name(endpoint: ResolvedWebhookEndpoint) -> str:
    header = endpoint.host_header
    if header.startswith('['):
        end = header.find(']')
        if end != -1:
            return header[1:end]
    if ':' in header:
        host, _, port_part = header.rpartition(':')
        if port_part.isdigit():
            return host
    return header


def post_resolved_webhook(
    endpoint: ResolvedWebhookEndpoint,
    *,
    body: bytes,
    headers: dict[str, str],
    timeout: float,
) -> WebhookPostResult:
    req_headers = dict(headers)
    req_headers['Host'] = endpoint.host_header
    if endpoint.scheme == 'https':
        context = ssl.create_default_context()
        server_name = _tls_server_name(endpoint)
        conn: HTTPConnection | HTTPSConnection = PinnedHTTPSConnection(
            server_name,
            endpoint.port,
            timeout=timeout,
            context=context,
            connect_host=endpoint.connect_host,
        )
    else:
        conn = HTTPConnection(endpoint.connect_host, endpoint.port, timeout=timeout)
    try:
        conn.request('POST', endpoint.path, body=body, headers=req_headers)
        response = conn.getresponse()
        status = int(response.status)
        excerpt = _read_response_excerpt(response)
        retry_raw = response.getheader('Retry-After')
        retry_after = parse_retry_after_header(retry_raw)
        return WebhookPostResult(status=status, excerpt=excerpt, retry_after_seconds=retry_after)
    finally:
        conn.close()


def post_webhook_url(
    url: str,
    *,
    body: bytes,
    headers: dict[str, str],
    timeout: float,
    allow_private: bool,
) -> WebhookPostResult:
    try:
        endpoint = resolve_webhook_endpoint(url, allow_private=allow_private)
    except SSRFError as exc:
        raise WebhookHTTPError(str(exc), permanent=True) from exc
    return post_resolved_webhook(endpoint, body=body, headers=headers, timeout=timeout)
