"""New HTTPS adapter used by the otherwise unchanged module-1 script.

Python/OpenSSL perform standard TLS, certificate validity, and hostname checks.
We additionally pin the exact pre-distributed certificate before sending data.
No custom cryptography, redirects, HTTP fallback, or system CA trust is used.
Each caller has its own copy so its uv project remains independently runnable.
"""
from contextlib import contextmanager
import hmac
from http.client import HTTPSConnection, HTTPException
from io import BytesIO
from pathlib import Path
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

CERTIFICATE_FILE = Path(__file__).with_name('server.crt')


@contextmanager
def tls_urlopen(request, timeout=15):
    url = urlsplit(request.full_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.fragment:
        raise ValueError('use an HTTPS URL without credentials or a fragment')
    # This certificate is the application's pre-distributed trust artifact.
    certificate = CERTIFICATE_FILE.read_text()
    expected = ssl.PEM_cert_to_DER_cert(certificate)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=certificate)
    context.set_alpn_protocols(['http/1.1'])
    connection = HTTPSConnection(url.hostname, url.port, timeout=timeout,
                                 context=context)
    try:
        # Authenticate first: no HTTP request or payload is sent by connect().
        connection.connect()
        actual = connection.sock.getpeercert(binary_form=True)
        if not hmac.compare_digest(actual, expected):
            raise ssl.SSLError('server certificate does not match the pinned certificate')
        target = url.path or '/'
        if url.query:
            target += '?' + url.query
        connection.request(request.get_method(), target, body=request.data,
                           headers=dict(request.header_items()))
        response = connection.getresponse()
        # Do not forward private data to another endpoint via a redirect.
        if response.status >= 300:
            raise HTTPError(request.full_url, response.status, response.reason,
                            response.headers, BytesIO(response.read()))
        with response:
            yield response
    except (OSError, HTTPException) as exc:
        # Preserve the original scripts' existing HTTP error reporting.
        if isinstance(exc, HTTPError):
            raise
        raise URLError(exc) from exc
    finally:
        connection.close()
