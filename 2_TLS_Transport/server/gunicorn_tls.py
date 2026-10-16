"""New Gunicorn settings: standard HTTPS, with a runtime-mounted private key.

Gunicorn imports the unchanged server:app. One worker preserves the in-memory
model; its threads share the existing model lock.
"""
import os
from pathlib import Path
import ssl

bind = '0.0.0.0:8000'
workers = 1
threads = 4
certfile = str(Path(__file__).with_name('server.crt'))
keyfile = os.environ.get('TLS_PRIVATE_KEY_FILE', '/run/secrets/tls_private_key')


def ssl_context(conf, default_ssl_context_factory):
    # Gunicorn loads the certificate and secret key into OpenSSL's TLS context.
    context = default_ssl_context_factory()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context
