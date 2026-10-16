"""Release application data only after local attestation and live TLS-key checks.

The TLS handshake is provisional until the Rust verifier approves the evidence
embedded in its leaf certificate. No HTTP request is sent before acceptance.
Never use CERT_NONE without this complete adapter. No HTTP fallback or redirects.
Each role has its own copy to remain an independent uv project.

Flow: load our expected policy -> receive a certificate during TLS -> ask the
local Rust verifier to check its evidence -> confirm the same live connection
-> send the original HTTP request. The certificate is not fetched with HTTP.
Python manages the connection; Rust parses and verifies the attestation.
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
    # The caller has already constructed an HTTP Request with weights/features.
    # This context manager delays sending that request until verification passes.
    def progress(message):
        if debug:
            print('[RA-TLS] ' + message, file=sys.stderr, flush=True)

    url = urlsplit(request.full_url)
    if (url.scheme != 'https' or not url.hostname or url.username
            or url.password or url.fragment):
        raise ValueError('use an HTTPS URL without credentials or a fragment')
    # 1. Load our trust inputs, independently of anything the server supplies.
    # policy.json contains the approved Compose and UKI hashes. json.loads only
    # parses the file here; it does not yet compare it with server evidence.
    # The verifier executable is also local, not downloaded from this endpoint.
    policy_file = Path(os.environ.get('ATTESTATION_POLICY', MODULE / 'policy.json')).resolve()
    verifier = Path(os.environ.get(
        'TDX_VERIFIER', MODULE / 'verifier/target/release/sec304-tdx-verifier')).resolve()
    progress('Load trusted local policy: ' + str(policy_file))
    policy = json.loads(policy_file.read_text())
    # 2. Set up provisional TLS. We cannot use ordinary CA/hostname validation
    # as our authentication rule: this server has an attestation-bearing identity.
    # CERT_NONE lets us receive it, but DOES NOT establish trust. The checks below
    # must succeed before sending any HTTP headers, coefficients, or features.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_alpn_protocols(['http/1.1'])
    connection = HTTPSConnection(url.hostname, url.port, timeout=150, context=context)
    try:
        progress('Open provisional TLS connection; application data withheld.')
        # connect() opens TCP and performs TLS. The server sends its certificate
        # as part of that handshake. No /certificate or /attestation GET is needed.
        connection.connect()
        # Extract the leaf certificate already received by TLS, as DER bytes.
        # This includes the public key and embedded dstack attestation extension.
        certificate = connection.sock.getpeercert(binary_form=True)
        # This hash identifies which certificate we gave Rust, not our Docker
        # image or approved workload. We check Rust's returned hash below.
        certificate_hash = hashlib.sha256(certificate).hexdigest()
        progress('Received server leaf certificate (UNVERIFIED), SHA-256: ' + certificate_hash)
        if debug:
            # PEM is the exact public certificate from the handshake, including
            # its evidence extension. It contains no TLS private key.
            print(ssl.DER_cert_to_PEM_cert(certificate), file=sys.stderr, flush=True)
        # 3. Pass the public certificate and trusted policy to the local Rust CLI.
        # certificate.rs parses X.509, extracts evidence, and computes the TLS
        # public-key binding. verification.rs checks Intel/Google signatures,
        # event chains, key binding, and measured values against the policy.
        # The temporary file is just the CLI input, never a private-key file.
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
            # check=True raises on a nonzero verifier exit. There is no request
            # release in that case. stdout contains JSON claims only on success.
        if debug and result.stderr:
            print(result.stderr, file=sys.stderr, end='', flush=True)
        claims = json.loads(result.stdout)
        # 4. Check the verifier's acceptance contract in Python too: expected
        # platform/status, our two approved hashes, and the exact certificate
        # supplied above. Python does not reimplement Rust's cryptography.
        if (claims.get('is_valid') is not True
                or claims.get('tee_variant') != 'dstack-gcp-tdx'
                or claims.get('tcb_status') != 'UpToDate'
                or claims.get('compose_hash') != policy['compose_hash']
                or claims.get('uki_authenticode_sha256') != policy['uki_authenticode_sha256']
                or not hmac.compare_digest(claims.get('certificate_sha256', ''), certificate_hash)):
            raise ValueError('verifier did not return the required policy/binding verdict')

        # 5. Keep verification and data release on the same live TLS connection.
        # A replacement connection would need its own certificate verification.
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
        # 6. This is the first line that sends the original HTTP request and its
        # private body. Everything above exchanged TLS/public evidence only.
        progress('Send application request on verified connection (body not logged).')
        connection.request(request.get_method(), target, body=request.data,
                           headers=dict(request.header_items()))
        response = connection.getresponse()
        progress('Received application HTTP status: ' + str(response.status))
        if response.status >= 300:
            raise HTTPError(request.full_url, response.status, response.reason,
                            response.headers, BytesIO(response.read()))
        with response:
            # Give the response back to the client script's `with` block so it
            # can read the prediction. HTTP errors remain application errors,
            # even if the preceding attestation checks succeeded.
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
        # Runs after the caller reads its response, and also after any failure.
        # Each invocation handles one connection; a later request starts afresh.
        progress('Close TLS connection.')
        connection.close()
