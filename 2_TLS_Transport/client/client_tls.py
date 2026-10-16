"""New entry point: reuse client.py's inputs/output, replace only its transport.

Run this file instead of client.py for HTTPS. The original HTTP script is kept
unchanged for comparison; the adapter pins the server certificate before POST.
"""
import sys

import client
from tls_transport import tls_urlopen


def main():
    # Explicitly wire the new adapter into the original script's request call.
    client.urlopen = tls_urlopen
    if not any(arg == '--url' or arg.startswith('--url=') for arg in sys.argv[1:]):
        sys.argv.extend(['--url', 'https://localhost:18043'])
    try:
        return client.main()
    except OSError as exc:
        print(f'TLS setup failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
