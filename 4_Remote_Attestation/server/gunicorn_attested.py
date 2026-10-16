"""HTTPS settings for a fresh, in-guest identity rather than a mounted old key.

One worker keeps the unchanged model's state in one process. Threads share it.
Never log request bodies or private key material.
"""
import ssl

bind = '0.0.0.0:8000'
workers = 1
threads = 4
timeout = 180  # Allow slow application requests; quote issuance occurs at startup.
keepalive = 180  # Keep the same TLS connection open during local verification.
certfile = '/run/sec304-tls/server.crt'
keyfile = '/run/sec304-tls/server.key'


def ssl_context(conf, default_ssl_context_factory):
    context = default_ssl_context_factory()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context
