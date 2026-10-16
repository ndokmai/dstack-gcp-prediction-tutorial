"""Identity startup contracts; mocked certificates are not hardware evidence."""
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
identity = importlib.import_module('tls_identity')


class ServerTests(unittest.TestCase):
    def test_requests_embedded_evidence(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps({
            'key': '-----BEGIN PRIVATE KEY-----\nTEST',
            'certificate_chain': ['-----BEGIN CERTIFICATE-----\nTEST'],
        }).encode()
        with patch.object(identity, 'GuestConnection', return_value=connection), \
                patch.object(identity.socket, 'socket'):
            identity.request_identity()
        args = connection.request.call_args.args
        self.assertEqual(args[:2], ('POST', '/GetTlsKey'))
        self.assertTrue(json.loads(args[2])['usage_ra_tls'])
        connection.close.assert_called_once()

    def test_guest_reconnects_only_to_unix_socket(self):
        with patch.object(identity.socket, 'socket') as factory:
            connection = identity.GuestConnection('localhost', timeout=90)
            connection.connect()
            connection.close()
            connection.connect()
        self.assertEqual(factory.call_count, 2)
        factory.assert_called_with(identity.socket.AF_UNIX, identity.socket.SOCK_STREAM)
        factory.return_value.connect.assert_called_with('/var/run/dstack.sock')

    def test_issuance_failure_prevents_startup(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 404
        connection.getresponse.return_value.read.return_value = b'Not found'
        with patch.object(identity, 'GuestConnection', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'TLS identity request failed'):
                identity.request_identity()
        self.assertEqual(connection.request.call_count, 1)
        self.assertEqual(connection.request.call_args.args[:2], ('POST', '/GetTlsKey'))
        connection.close.assert_called_once()

    def test_unavailable_agent_prevents_startup(self):
        with patch.object(identity.socket, 'socket') as factory:
            factory.return_value.connect.side_effect = OSError('no guest socket')
            with self.assertRaises(OSError):
                identity.request_identity()


if __name__ == '__main__':
    unittest.main()
