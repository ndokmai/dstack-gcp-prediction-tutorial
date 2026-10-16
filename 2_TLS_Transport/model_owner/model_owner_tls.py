"""New entry point: reuse model_owner.py, replace only the request transport.

Run this file instead of model_owner.py. File selection, exact upload bytes,
and readiness handling remain unchanged; server authentication precedes POST.
"""
import sys

import model_owner
from tls_transport import tls_urlopen


def main():
    # Keep the application workflow unchanged and inject the TLS adapter.
    model_owner.urlopen = tls_urlopen
    if not any(arg == '--url' or arg.startswith('--url=') for arg in sys.argv[1:]):
        sys.argv.extend(['--url', 'https://localhost:18043'])
    return model_owner.main()


if __name__ == '__main__':
    sys.exit(main())
