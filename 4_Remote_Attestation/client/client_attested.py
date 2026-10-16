"""Module-4 entry point: retain the existing role workflow, add attested TLS."""
import sys
import argparse
from functools import partial

import client
from attested_transport import attested_urlopen


def main():
    client.__doc__ = 'Send prediction features only after local RA-TLS verification.'
    # Change only the transport; model bytes and prediction inputs stay unchanged.
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--debug', action='store_true')
    debug_args, remaining = parser.parse_known_args()
    sys.argv[1:] = remaining
    if '--help' in remaining or '-h' in remaining:
        print('RA-TLS option: --debug shows progress and public server evidence.')
    client.urlopen = partial(attested_urlopen, debug=debug_args.debug)
    if not any(arg == '--url' or arg.startswith('--url=') for arg in sys.argv[1:]):
        sys.argv.extend(['--url', 'https://localhost:18043'])
    return client.main()


if __name__ == '__main__':
    sys.exit(main())
