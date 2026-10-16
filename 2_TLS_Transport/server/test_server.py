"""Check Flask's provisioning policy without opening a network listener.

From this directory: uv run python -m unittest -v
"""
import hashlib
import json
import unittest

from server import EXPECTED_MODEL_SHA256, create_app


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()
        # Synthetic test fixture representing the owner's private coefficients;
        # not an import/read from the owner's project.
        # Keep these exact bytes aligned with the server's approved-file hash.
        self.raw = (b'{\n  "bias": 500000,\n  "weights": {\n'
                    b'    "area_m2": 40000,\n    "bedrooms": 200000,\n'
                    b'    "age_years": -15000\n  }\n}\n')
        self.features = {'area_m2': 120, 'bedrooms': 3, 'age_years': 10}

    def upload(self, raw=None):
        return self.client.post('/model', data=self.raw if raw is None else raw,
                                content_type='application/json')

    def test_startup_and_provisioning(self):
        self.assertEqual(self.client.get('/health').json['model_ready'], False)
        self.assertEqual(self.client.post('/predict', json=self.features).status_code, 503)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), EXPECTED_MODEL_SHA256)
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.client.get('/health').json['model_ready'], True)
        self.assertEqual(self.client.post('/predict', json=self.features).json,
                         {'prediction_baht': 5750000})

    def test_changed_bytes_rejected_without_changing_state(self):
        changed = json.loads(self.raw)
        changed['bias'] += 1
        self.assertEqual(self.upload(json.dumps(changed).encode()).status_code, 403)
        self.assertEqual(self.upload(json.dumps(json.loads(self.raw)).encode()).status_code, 403)
        self.assertFalse(self.client.get('/health').json['model_ready'])
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.upload(b'{}').status_code, 403)
        self.assertEqual(self.client.post('/predict', json=self.features).json['prediction_baht'], 5750000)

    def test_invalid_predictions_and_request_size(self):
        self.upload()
        for features in ({}, [], {**self.features, 'area_m2': -1},
                         {**self.features, 'bedrooms': True},
                         {**self.features, 'area_m2': float('nan')}):
            with self.subTest(features=features):
                self.assertEqual(self.client.post('/predict', json=features).status_code, 400)
        self.assertEqual(self.client.post('/predict', data='{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post('/predict', data='text').status_code, 400)
        self.assertEqual(self.upload(b'x' * 4097).status_code, 413)
        self.assertEqual(self.client.get('/model').status_code, 405)

    def test_new_server_requires_provisioning_again(self):
        self.upload()
        fresh = create_app().test_client()
        self.assertFalse(fresh.get('/health').json['model_ready'])
        self.assertEqual(fresh.post('/predict', json=self.features).status_code, 503)


if __name__ == '__main__':
    unittest.main()
