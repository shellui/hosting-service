"""Tests for SSRF-safe HTTPS webhook transport (pinned connect + SNI)."""

from __future__ import annotations

import socket
import ssl
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.actions.ssrf import ResolvedWebhookEndpoint
from apps.actions.webhook_transport import PinnedHTTPSConnection, post_resolved_webhook


class PinnedHTTPSConnectionUnitTests(SimpleTestCase):
    def test_connect_dials_pinned_ip_and_wraps_with_server_hostname(self):
        recorded: dict = {}

        def fake_create_connection(address, timeout, source_address):
            recorded['address'] = address
            recorded['timeout'] = timeout
            return MagicMock(name='tcp_sock')

        def fake_wrap(self, sock, server_hostname=None):
            recorded['sock'] = sock
            recorded['server_hostname'] = server_hostname
            return MagicMock(name='tls_sock')

        context = ssl.create_default_context()
        conn = PinnedHTTPSConnection(
            'example.com',
            443,
            timeout=5.0,
            context=context,
            connect_host='93.184.216.34',
        )

        with patch('apps.actions.webhook_transport.socket.create_connection', fake_create_connection):
            with patch.object(ssl.SSLContext, 'wrap_socket', fake_wrap):
                conn.connect()

        self.assertEqual(recorded['address'], ('93.184.216.34', 443))
        self.assertEqual(recorded['server_hostname'], 'example.com')

    def test_connect_supports_ipv6_pinned_address(self):
        recorded: dict = {}

        def fake_create_connection(address, timeout, source_address):
            recorded['address'] = address
            return MagicMock()

        conn = PinnedHTTPSConnection(
            '::1',
            443,
            timeout=3.0,
            context=ssl.create_default_context(),
            connect_host='::1',
        )
        with patch('apps.actions.webhook_transport.socket.create_connection', fake_create_connection):
            with patch.object(ssl.SSLContext, 'wrap_socket', lambda *a, **k: MagicMock()):
                conn.connect()
        self.assertEqual(recorded['address'][0], '::1')


def _generate_localhost_cert(tmp: Path) -> tuple[Path, Path]:
    key = tmp / 'key.pem'
    cert = tmp / 'cert.pem'
    subprocess.run(
        [
            'openssl',
            'req',
            '-x509',
            '-newkey',
            'rsa:2048',
            '-keyout',
            str(key),
            '-out',
            str(cert),
            '-days',
            '1',
            '-nodes',
            '-subj',
            '/CN=localhost',
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


class LocalHTTPSWebhookTransportTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(cls._tmp.name)
        cls._cert_file, cls._key_file = _generate_localhost_cert(tmp_path)
        cls._server = HTTPServer(('127.0.0.1', 0), _EchoHandler)
        cls._port = cls._server.server_address[1]
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cls._cert_file), keyfile=str(cls._key_file))
        cls._server.socket = context.wrap_socket(cls._server.socket, server_side=True)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._tmp.cleanup()

    @override_settings(ACTIONS_WEBHOOK_ALLOW_PRIVATE=True)
    def test_localhost_https_round_trip_via_pinned_connection(self):
        endpoint = ResolvedWebhookEndpoint(
            original_url=f'https://localhost:{self._port}/hook',
            scheme='https',
            connect_host='127.0.0.1',
            port=self._port,
            host_header='localhost',
            path='/hook',
        )
        trust_local = ssl.create_default_context()
        trust_local.load_verify_locations(cafile=str(self._cert_file))
        with patch('apps.actions.webhook_transport.ssl.create_default_context', return_value=trust_local):
            result = post_resolved_webhook(
                endpoint,
                body=b'{"ok":true}',
                headers={'Content-Type': 'application/json'},
                timeout=5.0,
            )
        self.assertEqual(result.status, 200)

    @override_settings(ACTIONS_WEBHOOK_ALLOW_PRIVATE=True)
    def test_hostname_mismatch_fails_tls_verification(self):
        endpoint = ResolvedWebhookEndpoint(
            original_url=f'https://localhost:{self._port}/hook',
            scheme='https',
            connect_host='127.0.0.1',
            port=self._port,
            host_header='wrong-host.example',
            path='/hook',
        )
        trust_local = ssl.create_default_context()
        trust_local.load_verify_locations(cafile=str(self._cert_file))
        with patch('apps.actions.webhook_transport.ssl.create_default_context', return_value=trust_local):
            with self.assertRaises(ssl.SSLCertVerificationError):
                post_resolved_webhook(
                    endpoint,
                    body=b'{}',
                    headers={'Content-Type': 'application/json'},
                    timeout=5.0,
                )


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, format, *args):
        return
