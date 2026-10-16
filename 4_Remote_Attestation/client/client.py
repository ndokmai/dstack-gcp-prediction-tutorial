"""Stage 1 client: send synthetic property features and display a prediction.

Runs on the host with Python 3; requires no third-party packages or model file.
This HTTP client does not authenticate the server. Later stages add evidence
verification and secure transport before sending confidential inputs.
"""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18000')
    parser.add_argument('--area-m2', type=float, default=120)
    parser.add_argument('--bedrooms', type=float, default=3)
    parser.add_argument('--age-years', type=float, default=10)
    args = parser.parse_args()
    features = {'area_m2': args.area_m2, 'bedrooms': args.bedrooms,
                'age_years': args.age_years}
    try:
        request = Request(args.url.rstrip('/') + '/predict',
                          data=json.dumps(features, allow_nan=False).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
        # The client receives the result, not the model coefficients.
        print(json.dumps(result))
    except HTTPError as exc:
        print(f'Server rejected request (HTTP {exc.code}): {exc.read().decode()}', file=sys.stderr)
        return 1
    except (URLError, TimeoutError, ValueError) as exc:
        print(f'Request failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
