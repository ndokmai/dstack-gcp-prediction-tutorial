"""Exercise the added transport with real TLS sockets and temporary identities.

From the module root: uv run --project server python -m unittest discover -s tests -v
These tests do not change the application certificate or read its private key.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from flask import Flask, request
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        directory = Path(cls.temporary.name)
        cls.certificates = []
        for name in ('server', 'untrusted'):
            key, cert = directory / f'{name}.key', directory / f'{name}.crt'
            subprocess.run([
                'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-days', '1', '-subj', '/CN=localhost',
                '-addext', 'subjectAltName=DNS:localhost',
                '-addext', 'basicConstraints=critical,CA:FALSE',
                '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment',
                '-addext', 'extendedKeyUsage=serverAuth',
                '-keyout', str(key), '-out', str(cert),
            ], check=True, capture_output=True)
            cls.certificates.append(cert)
        cls.received = []
        app = Flask(__name__)

        @app.post('/echo')
        def echo():
            cls.received.append(request.get_data())
            return {'received': True}

        @app.post('/redirect')
        def redirect():
            return '', 307, {'Location': '/echo'}

        cls.server = make_server('127.0.0.1', 0, app,
                                 ssl_context=(str(directory / 'server.crt'),
                                              str(directory / 'server.key')))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'https://localhost:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.temporary.cleanup()

    def test_each_role_transport(self):
        for role in ('client', 'model_owner'):
            with self.subTest(role=role):
                spec = importlib.util.spec_from_file_location(
                    f'{role}_transport', ROOT / role / 'tls_transport.py')
                transport = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(transport)
                with patch.object(transport, 'CERTIFICATE_FILE', self.certificates[0]):
                    req = Request(self.base + '/echo', data=b'synthetic payload')
                    with transport.tls_urlopen(req) as response:
                        self.assertEqual(json.load(response), {'received': True})
                    self.assertEqual(self.received[-1], b'synthetic payload')
                    # HTTP is rejected before any network request.
                    before = len(self.received)
                    with self.assertRaises(ValueError):
                        with transport.tls_urlopen(Request('http://localhost/echo', data=b'x')):
                            pass
                    # The same trusted certificate cannot authenticate another hostname.
                    with self.assertRaises(URLError):
                        with transport.tls_urlopen(Request(
                                self.base.replace('localhost', '127.0.0.1') + '/echo', data=b'x')):
                            pass
                    self.assertEqual(len(self.received), before)
                    # Redirects are returned as errors, never followed.
                    with self.assertRaises(HTTPError) as caught:
                        with transport.tls_urlopen(Request(self.base + '/redirect', data=b'x')):
                            pass
                    self.assertEqual(caught.exception.code, 307)
                    self.assertEqual(len(self.received), before)
                with patch.object(transport, 'CERTIFICATE_FILE', self.certificates[1]):
                    before = len(self.received)
                    with self.assertRaises(URLError):
                        with transport.tls_urlopen(Request(self.base + '/echo', data=b'x')):
                            pass
                    self.assertEqual(len(self.received), before)


if __name__ == '__main__':
    unittest.main()
