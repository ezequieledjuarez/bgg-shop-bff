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


def test_optional_operation_key_and_login_no_store_are_documented():
    spec = pathlib.Path(__file__).resolve().parents[1] / 'specs' / 'openapi.yaml'
    schema = yaml.safe_load(spec.read_text(encoding='utf-8'))
    gift_card = schema['paths']['/api/v1/admin/gift-cards']['post']
    assert {'XOpKey': []} in gift_card['security']
    login = schema['paths']['/api/v1/auth/login']['post']['responses']['200']
    assert 'no-store' in login['headers']['Cache-Control']['schema']['enum']


def test_admin_stock_movement_contract_requires_uuid_direction_and_quantity():
    spec = pathlib.Path(__file__).resolve().parents[1] / 'specs' / 'openapi.yaml'
    schema = yaml.safe_load(spec.read_text(encoding='utf-8'))
    request = schema['components']['schemas']['AdminAdjustStockRequest']
    assert set(request['required']) == {'movement_id', 'direction', 'quantity'}
    assert request['properties']['movement_id']['format'] == 'uuid'
    assert set(request['properties']['direction']['enum']) == {'IN', 'OUT'}
    assert request['properties']['quantity']['minimum'] == 1
    responses = schema['paths']['/api/v1/admin/products/{product_id}/stock']['post']['responses']
    assert {'200', '202', '400', '401', '403', '404', '409', '502'} <= set(responses)
    assert responses['200']['content']['application/json']['schema']['$ref'] == '#/components/schemas/AdminStockMovementResult'
    assert responses['409']['content']['application/json']['schema']['$ref'] == '#/components/schemas/AdminStockMovementError'


def test_global_promotion_contract_preserves_optional_nullable_product_and_selection_rules():
    spec = pathlib.Path(__file__).resolve().parents[1] / 'specs' / 'openapi.yaml'
    schema = yaml.safe_load(spec.read_text(encoding='utf-8'))
    fields = schema['components']['schemas']['AdminPromotionFields']
    product_field = fields['properties']['product_bgg_id']
    assert product_field['nullable'] is True
    assert 'product_bgg_id' not in fields.get('required', [])
    for path in (
        '/api/v1/admin/promotions',
        '/api/v1/admin/promotions/{promotion_id}',
    ):
        description = ' '.join(
            schema['paths'][path][method]['description']
            for method in ('get', 'post', 'put')
            if method in schema['paths'][path]
        ).lower()
        assert 'global' in description
        assert 'product-specific' in description
        assert 'highest eligible global' in description
        assert 'do not stack' in description or 'never stack' in description
        assert 'coupon-linked' in description
