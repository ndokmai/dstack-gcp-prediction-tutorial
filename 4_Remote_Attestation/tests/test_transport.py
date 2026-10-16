"""Contract tests with mocked evidence verification, NOT hardware attestation tests.

Exercise both independent callers and prove failed verification prevents the
private application POST. No real keys, network listeners, or cloud resources.
"""
import importlib.util
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]


class Socket:
    def getpeercert(self, binary_form=False):
        return b'public-test-certificate'

    def settimeout(self, timeout):
        pass


class Response:
    status = 200

    def __init__(self, body):
        self.body = body

    def read(self, limit=None):
        return self.body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Connection:
    def __init__(self):
        self.sock = Socket()
        self.requests = []
        self.closed_after_challenge = False

    def connect(self):
        pass

    def request(self, method, target, body=None, headers=None):
        self.requests.append((target, body))

    def getresponse(self):
        return Response(b'{"prediction":5750000}')

    def close(self):
        pass


class TransportTests(unittest.TestCase):
    def exercise(self, role, failure=None, debug=False):
        spec = importlib.util.spec_from_file_location(
            'transport_' + role, ROOT / role / 'attested_transport.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection = Connection()
        connection.closed_after_challenge = failure == 'closed'
        policy = {'compose_hash': '11' * 32, 'uki_authenticode_sha256': '22' * 32}

        def verify(args, **kwargs):
            if failure == 'verifier':
                raise subprocess.CalledProcessError(1, args, stderr='Error: unapproved Compose hash')
            if failure == 'missing':
                raise FileNotFoundError('verifier missing')
            if failure == 'timeout':
                raise subprocess.TimeoutExpired(args, 130)
            claims = dict(policy, is_valid=True, tee_variant='dstack-gcp-tdx',
                          tcb_status='UpToDate', certificate_sha256=module.hashlib.sha256(b'public-test-certificate').hexdigest())
            if failure == 'binding':
                claims['certificate_sha256'] = '00' * 32
            if failure == 'compose':
                claims['compose_hash'] = '00' * 32
            if failure == 'uki':
                claims['uki_authenticode_sha256'] = '00' * 32
            if failure == 'tcb':
                claims['tcb_status'] = 'OutOfDate'
            if failure == 'platform':
                claims['tee_variant'] = 'other'
            if failure == 'malformed':
                return subprocess.CompletedProcess(args, 0, 'not JSON', '')
            if failure == 'closed':
                connection.sock = None
            return subprocess.CompletedProcess(args, 0, json.dumps(claims), '')

        with tempfile.TemporaryDirectory() as directory:
            policy_file = Path(directory) / 'policy.json'
            policy_file.write_text(json.dumps(policy))
            with patch.dict(module.os.environ, {'ATTESTATION_POLICY': str(policy_file)}), \
                    patch.object(module, 'HTTPSConnection', return_value=connection), \
                    patch.object(connection.sock, 'getpeercert', side_effect=(
                        [b'public-test-certificate', b'wrong-live-certificate'] if failure == 'key'
                        else [b'public-test-certificate', b'public-test-certificate'])), \
                    patch.object(module.subprocess, 'run', side_effect=verify), \
                    patch.object(module.sys, 'stderr', new_callable=StringIO) as console:
                private = b'PRIVATE-APPLICATION-BODY'
                request = Request('https://localhost:18043/model', data=private, method='POST')
                if failure:
                    with self.assertRaises((ValueError, URLError)) as error:
                        with module.attested_urlopen(request, debug=debug):
                            pass
                    if failure == 'verifier':
                        self.assertIn('unapproved Compose hash', str(error.exception))
                        self.assertNotIn(private.decode(), str(error.exception))
                    self.assertEqual(connection.requests, [])
                    if not debug:
                        self.assertEqual(console.getvalue(), '')
                    self.assertNotIn('Verification accepted', console.getvalue())
                    self.assertNotIn(private, [body for _, body in connection.requests])
                else:
                    with module.attested_urlopen(request, debug=debug) as response:
                        self.assertEqual(response.status, 200)
                    self.assertEqual(connection.requests[-1], ('/model', private))
                    if debug:
                        self.assertIn('Verification accepted', console.getvalue())
                        self.assertIn('"certificate_sha256"', console.getvalue())
                        self.assertIn('BEGIN CERTIFICATE', console.getvalue())
                        self.assertIn('UNVERIFIED', console.getvalue())
                    else:
                        self.assertEqual(console.getvalue(), '')
                    self.assertNotIn(private.decode(), console.getvalue())

    def test_both_roles_send_only_after_acceptance(self):
        for role in ('client', 'model_owner'):
            with self.subTest(role=role):
                self.exercise(role)

    def test_both_roles_fail_closed(self):
        for role in ('client', 'model_owner'):
            for failure in ('verifier', 'missing', 'timeout', 'binding', 'compose', 'uki', 'tcb', 'platform', 'closed', 'key', 'malformed'):
                with self.subTest(role=role, failure=failure):
                    self.exercise(role, failure)

    def test_debug_shows_public_evidence_only(self):
        for role in ('client', 'model_owner'):
            self.exercise(role, debug=True)
            self.exercise(role, 'verifier', debug=True)


if __name__ == '__main__':
    unittest.main()
