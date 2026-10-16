"""Release application data only after local attestation and live TLS-key checks.

The TLS handshake is provisional until the Rust verifier approves the evidence
embedded in its leaf certificate. No HTTP request is sent before acceptance.
Never use CERT_NONE without this complete adapter. No HTTP fallback or redirects.
Each role has its own copy to remain an independent uv project.
"""
from contextlib import contextmanager
import hashlib
import hmac
from http.client import HTTPSConnection, HTTPException
from io import BytesIO
import json
import os
from pathlib import Path
import ssl
import sys
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

MODULE = Path(__file__).resolve().parent.parent


@contextmanager
def attested_urlopen(request, timeout=15, *, debug=False):
    def progress(message):
        if debug:
            print('[RA-TLS] ' + message, file=sys.stderr, flush=True)

    url = urlsplit(request.full_url)
    if (url.scheme != 'https' or not url.hostname or url.username
            or url.password or url.fragment):
        raise ValueError('use an HTTPS URL without credentials or a fragment')
    # Both paths are local trust inputs; do not download them from this endpoint.
    policy_file = Path(os.environ.get('ATTESTATION_POLICY', MODULE / 'policy.json')).resolve()
    verifier = Path(os.environ.get(
        'TDX_VERIFIER', MODULE / 'verifier/target/release/sec304-tdx-verifier')).resolve()
    progress('Load trusted local policy: ' + str(policy_file))
    policy = json.loads(policy_file.read_text())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_alpn_protocols(['http/1.1'])
    connection = HTTPSConnection(url.hostname, url.port, timeout=150, context=context)
    try:
        progress('Open provisional TLS connection; application data withheld.')
        connection.connect()
        certificate = connection.sock.getpeercert(binary_form=True)
        certificate_hash = hashlib.sha256(certificate).hexdigest()
        progress('Received server leaf certificate (UNVERIFIED), SHA-256: ' + certificate_hash)
        if debug:
            # PEM is the exact public certificate from the handshake, including
            # its evidence extension. It contains no TLS private key.
            print(ssl.DER_cert_to_PEM_cert(certificate), file=sys.stderr, flush=True)
        # Read evidence from this actual TLS certificate, not a separate endpoint.
        with tempfile.TemporaryDirectory(prefix='sec304-certificate-') as directory:
            certificate_file = Path(directory) / 'server.der'
            certificate_file.write_bytes(certificate)  # Public certificate only.
            progress('Run local Rust verifier on certificate and policy.')
            command = [str(verifier), str(certificate_file), str(policy_file)]
            if debug:
                command.append('--debug')
            result = subprocess.run(
                command,
                capture_output=True, text=True, timeout=130, check=True)
        if debug and result.stderr:
            print(result.stderr, file=sys.stderr, end='', flush=True)
        claims = json.loads(result.stdout)
        if (claims.get('is_valid') is not True
                or claims.get('tee_variant') != 'dstack-gcp-tdx'
                or claims.get('tcb_status') != 'UpToDate'
                or claims.get('compose_hash') != policy['compose_hash']
                or claims.get('uki_authenticode_sha256') != policy['uki_authenticode_sha256']
                or not hmac.compare_digest(claims.get('certificate_sha256', ''), certificate_hash)):
            raise ValueError('verifier did not return the required policy/binding verdict')

        # Never implicitly reconnect and send private data on an unchecked session.
        if connection.sock is None:
            raise ValueError('server closed the verified connection; retry from the start')
        if not hmac.compare_digest(
                connection.sock.getpeercert(binary_form=True), certificate):
            raise ValueError('live TLS certificate changed after verification')
        # Print only authenticated public claims, never model inputs or TLS secrets.
        # stderr leaves the application's stdout available for its own result.
        progress('Verification accepted; same live TLS certificate confirmed.')
        if debug:
            print(json.dumps(claims, indent=2), file=sys.stderr, flush=True)
        connection.sock.settimeout(timeout)
        target = url.path or '/'
        if url.query:
            target += '?' + url.query
        # Only now is the original request (weights/features) submitted.
        progress('Send application request on verified connection (body not logged).')
        connection.request(request.get_method(), target, body=request.data,
                           headers=dict(request.header_items()))
        response = connection.getresponse()
        progress('Received application HTTP status: ' + str(response.status))
        if response.status >= 300:
            raise HTTPError(request.full_url, response.status, response.reason,
                            response.headers, BytesIO(response.read()))
        with response:
            yield response
    except (OSError, HTTPException, subprocess.SubprocessError) as exc:
        if isinstance(exc, HTTPError):
            raise
        # The verifier receives only public certificate/policy inputs. Show its
        # bounded diagnostic, never application bodies or captured stdout.
        if isinstance(exc, subprocess.CalledProcessError):
            if debug and exc.stderr:
                print(exc.stderr, file=sys.stderr, end='', flush=True)
            diagnostic = ' '.join((exc.stderr or '').split())[:2000]
            reason = 'verifier rejected certificate: ' + (diagnostic or 'no diagnostic')
        else:
            reason = str(exc)
        raise URLError('attestation/TLS failed; no unchecked fallback: ' + reason) from exc
    finally:
        progress('Close TLS connection.')
        connection.close()
