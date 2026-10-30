import pathlib

import yaml

from src.dtos.orders import _ADDRESS_LIMITS


def test_openapi_includes_refresh_path():
    spec = pathlib.Path(__file__).resolve().parents[1] / 'specs' / 'openapi.yaml'
    text = spec.read_text(encoding='utf-8')
    assert '/api/v1/auth/refresh:' in text
    # ensure response schema name present
    assert 'AuthRefreshResponse' in text


def test_shipping_address_limits_match_checkout_validator():
    spec = pathlib.Path(__file__).resolve().parents[1] / 'specs' / 'openapi.yaml'
    schema = yaml.safe_load(spec.read_text(encoding='utf-8'))
    properties = schema['components']['schemas']['ShippingAddress']['properties']
    expected = {'recipient': 250, 'street': 500, 'city': 150, 'postal_code': 32, 'phone': 50}
    assert {name: value['maxLength'] for name, value in properties.items()} == expected
    assert _ADDRESS_LIMITS == expected


def test_retry_payment_documents_pending_conflict():
    spec = pathlib.Path(__file__).resolve().parents[1] / 'specs' / 'openapi.yaml'
    schema = yaml.safe_load(spec.read_text(encoding='utf-8'))
    response = schema['paths']['/api/v1/orders/{order_id}/retry-payment']['post']['responses']['409']
    assert 'PENDING_PAYMENT' in response['description']
    assert 'PAYMENT_REQUIRES_REVIEW' in response['description']
    assert response['content']['application/json']['schema']['$ref'] == '#/components/schemas/OrderErrorResponse'
