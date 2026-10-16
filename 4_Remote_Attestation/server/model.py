"""Small, transport-independent house-price model for the prediction server.

The same inference function can be used in later HTTP, TLS, and attested stages.
Coefficients are supplied by the model owner; no network or Docker logic lives here.
"""
import math

FEATURES = ('area_m2', 'bedrooms', 'age_years')


def number(value):
    # JSON booleans are not numeric features, even though Python treats bool as int.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('values must be numbers')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError('values must be finite numbers')
    return value


def validate_model(model):
    """Validate an uploaded model and return a fresh copy of its coefficients."""
    if not isinstance(model, dict) or set(model) != {'bias', 'weights'}:
        raise ValueError('model must contain exactly bias and weights')
    if not isinstance(model['weights'], dict) or set(model['weights']) != set(FEATURES):
        raise ValueError('model must contain exactly the supported feature weights')
    number(model['bias'])
    for weight in model['weights'].values():
        number(weight)
    return {'bias': model['bias'], 'weights': dict(model['weights'])}


def predict(features, model):
    """Return a prediction using client features and server-side coefficients."""
    if not isinstance(features, dict) or set(features) != set(FEATURES):
        raise ValueError('provide exactly area_m2, bedrooms, and age_years')
    for value in features.values():
        if number(value) < 0:
            raise ValueError('features must be nonnegative')
    prediction = model['bias'] + sum(
        features[name] * model['weights'][name] for name in FEATURES
    )
    number(prediction)
    return {'prediction_baht': round(prediction, 2)}
