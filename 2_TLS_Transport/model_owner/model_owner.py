"""Provision the server with model weights from the model owner's local file.

The synthetic weights represent the owner's private model coefficients.
Stage 1 sends them over plain HTTP. In later modules this script
will verify attestation and establish a secure channel before releasing weights.
The model owner is a separate role from the prediction client, even when both
scripts run on the same laptop for this tutorial. No private weights are logged.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18000')
    parser.add_argument('--model', type=Path,
                        default=Path(__file__).with_name('model.example.json'))
    args = parser.parse_args()
    try:
        raw = args.model.read_bytes()
        # Check JSON syntax locally; the server enforces the pinned file hash
        # and validates coefficient structure. No server code is needed here.
        json.loads(raw)
        # Send exact file bytes: reformatting JSON would change the approved hash.
        # Later: verify the TEE and establish a secure connection before upload.
        # The server's pinned hash checks content, not the sender's identity.
        request = Request(args.url.rstrip('/') + '/model',
                          data=raw,
                          headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
        if result.get('model_ready') is not True:
            raise ValueError('server did not confirm provisioning')
        print('Model provisioned successfully.')
    except HTTPError as exc:
        print(f'Server rejected upload (HTTP {exc.code}): {exc.read().decode()}', file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f'Provisioning failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
