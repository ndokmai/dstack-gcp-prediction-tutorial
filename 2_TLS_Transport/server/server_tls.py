"""New local HTTPS entry point; the module-1 Flask application is unchanged.

The public certificate is part of this application. Supply its matching private
key at runtime, never in the image. Docker uses Gunicorn instead of this runner.
"""
import argparse
import os
from pathlib import Path
import ssl

from server import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', type=Path,
                        default=os.environ.get('TLS_PRIVATE_KEY_FILE'))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8443)
    args = parser.parse_args()
    if args.key is None:
        parser.error('provide --key FILE or TLS_PRIVATE_KEY_FILE')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # OpenSSL checks that the certificate and runtime private key match.
    context.load_cert_chain(Path(__file__).with_name('server.crt'), args.key)
    app.run(host=args.host, port=args.port, ssl_context=context,
            debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
