"""Request a fresh RA-TLS identity from dstack before starting the web server.

The guest agent generates the key and obtains hardware evidence. This code only
stores the returned PEM files in private runtime storage; it never prints keys.
Without a real guest agent, startup fails rather than using a local fallback.
"""
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import time


class GuestConnection(http.client.HTTPConnection):
    """Keep every connection/reconnection on the local guest-agent socket."""

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/dstack.sock')


def request_identity():
    # Request a fresh key and attestation-bearing certificate from the guest.
    endpoint = '/GetTlsKey'
    print(f'[RA-TLS identity] Requesting TLS identity via {endpoint}',
          file=sys.stderr, flush=True)
    connection = GuestConnection('localhost', timeout=90)
    try:
        connection.connect()
        now = int(time.time())
        connection.request('POST', endpoint, json.dumps({
            'subject': 'attested-server',
            'usage_ra_tls': True,
            'usage_server_auth': True,
            'usage_client_auth': False,
            'not_before': now - 60,
            'not_after': now + 86400,
        }), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read(22 * 1024 * 1024 + 1)
        if response.status != 200 or len(body) > 22 * 1024 * 1024:
            raise RuntimeError(f'dstack TLS identity request failed at {endpoint} (no API fallback)')
        identity = json.loads(body)
        if (not isinstance(identity.get('key'), str)
                or not identity['key'].startswith('-----BEGIN PRIVATE KEY-----')
                or not isinstance(identity.get('certificate_chain'), list)
                or not identity['certificate_chain']
                or any(not isinstance(cert, str) or not cert.startswith(
                    '-----BEGIN CERTIFICATE-----') for cert in identity['certificate_chain'])):
            raise RuntimeError('invalid dstack identity response')
        print(f'[RA-TLS identity] TLS identity received successfully via {endpoint}',
              file=sys.stderr, flush=True)
        return identity
    finally:
        connection.close()


def main():
    os.umask(0o077)
    identity = request_identity()
    directory = Path('/run/sec304-tls')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    (directory / 'server.key').write_text(identity['key'])
    (directory / 'server.crt').write_text('\n'.join(identity['certificate_chain']))


if __name__ == '__main__':
    main()
