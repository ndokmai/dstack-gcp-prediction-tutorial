"""Flask prediction service with a pinned model-file hash.

Run locally with uv; the Docker image serves this app using one Gunicorn worker.
The model owner provisions weights once, then clients can request predictions.
This stage uses plain HTTP with synthetic data; TLS/attestation come later.
"""
import hashlib
import hmac
import json
import os
import threading

from flask import Flask, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from model import predict, validate_model

# Commit to exact approved bytes, including whitespace and final newline.
# Approving another model requires a reviewed code change and image rebuild.
EXPECTED_MODEL_SHA256 = '653bfcb49975bb472c52ec031a75dc3df51acdc34496d979cdfa66a8f18e4701'


def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 4096
    # Weights live in one process's memory and disappear when it restarts.
    model = None
    model_lock = threading.Lock()

    @app.get('/health')
    def health():
        with model_lock:
            ready = model is not None
        return {'status': 'ok', 'model_ready': ready}

    @app.post('/model')
    def provision_model():
        nonlocal model
        # Hash original upload bytes before parsing. The owner cannot choose
        # the expected digest, and formatting changes alter the hash.
        raw = request.get_data()
        actual = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual, EXPECTED_MODEL_SHA256):
            return {'error': 'model file does not match the approved SHA-256 hash'}, 403
        try:
            uploaded = validate_model(json.loads(raw))
        except (ValueError, OverflowError):
            return {'error': 'invalid approved model format'}, 400
        with model_lock:
            if model is not None:
                return {'error': 'model already provisioned; restart to provision again'}, 409
            model = uploaded
        # Return readiness without weights or a client-side model-hash check.
        return {'model_ready': True}

    @app.post('/predict')
    def prediction():
        with model_lock:
            current = model
        if current is None:
            return {'error': 'model not provisioned; run model_owner.py first'}, 503
        try:
            return predict(request.get_json(), current)
        except (ValueError, OverflowError, BadRequest, UnsupportedMediaType):
            return {'error': 'invalid features: provide three finite, nonnegative numbers named area_m2, bedrooms, age_years'}, 400

    @app.errorhandler(413)
    def too_large(error):
        return {'error': 'request exceeds 4096 bytes'}, 413

    @app.errorhandler(404)
    def not_found(error):
        return {'error': 'unknown route'}, 404

    return app


# Gunicorn imports this object as server:app without starting a development server.
app = create_app()

if __name__ == '__main__':
    # Local development only: disable debug/reloader for predictable model state.
    app.run(host=os.environ.get('HOST', '127.0.0.1'),
            port=int(os.environ.get('PORT', '8000')),
            debug=False, use_reloader=False)
