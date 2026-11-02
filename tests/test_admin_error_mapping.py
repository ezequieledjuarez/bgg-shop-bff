from unittest.mock import patch

import pytest

from app import app


def test_create_product_maps_user_error_to_400_with_field():
    client = app.test_client()
    err = Exception()

    def raise_upstream(payload):
        from src.proxy import UpstreamError

        raise UpstreamError("Invalid name", "INVALID_NAME", field="name", user_error=True)

    valid_payload = {"name": "Valid name", "price": 10.0, "quantity": 1}
    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_products_controller.admin_create_product_service", side_effect=raise_upstream):
            resp = client.post("/api/v1/admin/products", json=valid_payload, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "errors" in body and isinstance(body["errors"], list)
    first = body["errors"][0]
    assert first["field"] == "name"
    assert first["code"] == "INVALID_NAME"


@pytest.mark.parametrize("method,path,service,payload", [
    ("POST", "/api/v1/admin/products", "admin_create_product_service", {"name": "Game", "price": 10, "quantity": 1}),
    ("PUT", "/api/v1/admin/products/1", "admin_update_product_service", {"name": "Game"}),
])
@pytest.mark.parametrize("code,field,expected_status", [
    ("NAME_REQUIRED", ["name"], 400),
    ("SERVER_ERROR", ["synthetic-private-field"], 502),
    ("synthetic-private-code", ["synthetic-private-field"], 502),
])
def test_product_user_errors_do_not_expose_upstream_details(method, path, service, payload, code, field, expected_status):
    from src.proxy import UpstreamError

    secret = "synthetic-private-upstream-message"
    with patch("src.proxy.check_admin", return_value=True), \
            patch(f"src.controllers.admin_products_controller.{service}", side_effect=UpstreamError(secret, code, field=field, user_error=True)):
        response = app.test_client().open(path, method=method, json=payload, headers={"Authorization": "Bearer token"})
    assert response.status_code == expected_status
    body = response.get_data(as_text=True)
    assert secret not in body
    assert "synthetic-private-field" not in body
    assert "synthetic-private-code" not in body
    if code == "NAME_REQUIRED":
        assert response.get_json()["errors"] == [{"field": "name", "code": "NAME_REQUIRED", "message": "Name is required"}]


@pytest.mark.parametrize("method,path,service,payload", [
    ("POST", "/api/v1/admin/products", "admin_create_product_service", {"name": "Game", "price": 10, "quantity": 1}),
    ("PUT", "/api/v1/admin/products/1", "admin_update_product_service", {"name": "Game"}),
])
@pytest.mark.parametrize("code", ["UNAUTHENTICATED", "FORBIDDEN", "PRODUCT_NOT_FOUND"])
def test_product_upstream_status_is_sanitized_and_matches_contract(method, path, service, payload, code):
    from src.proxy import UpstreamError

    expected = {"UNAUTHENTICATED": 401, "FORBIDDEN": 403, "PRODUCT_NOT_FOUND": 404 if method == "PUT" else 502}
    with patch("src.proxy.check_admin", return_value=True), \
            patch(f"src.controllers.admin_products_controller.{service}", side_effect=UpstreamError("synthetic-private-message", code, field="synthetic-private-field", user_error=True)):
        response = app.test_client().open(path, method=method, json=payload, headers={"Authorization": "Bearer token"})
    assert response.status_code == expected[code]
    assert "synthetic-private" not in response.get_data(as_text=True)


@pytest.mark.parametrize("method,path,service,payload", [
    ("POST", "/api/v1/admin/products", "admin_create_product_service", {"name": "Game", "price": 10, "quantity": 1}),
    ("PUT", "/api/v1/admin/products/1", "admin_update_product_service", {"name": "Game"}),
])
@pytest.mark.parametrize("code,message", [
    ("DUPLICATE", "Product conflicts with existing data"),
    ("NO_OP", "At least one field must be provided"),
])
def test_product_business_error_uses_static_public_response(method, path, service, payload, code, message):
    from src.proxy import UpstreamError

    with patch("src.proxy.check_admin", return_value=True), \
            patch(f"src.controllers.admin_products_controller.{service}", side_effect=UpstreamError("synthetic-private-message", code, field="synthetic-private-field", user_error=True)):
        response = app.test_client().open(path, method=method, json=payload, headers={"Authorization": "Bearer token"})
    assert response.status_code == 400
    assert response.get_json() == {"errors": [{"code": code, "message": message}]}


def test_adjust_stock_maps_missing_product_to_404():
    client = app.test_client()

    def raise_upstream(product_id, movement_id, direction, quantity, token):
        from src.proxy import UpstreamError

        raise UpstreamError("private detail", "NOT_FOUND", user_error=True)

    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_products_controller.adjust_product_stock_service", side_effect=raise_upstream):
            resp = client.post(
                "/api/v1/admin/products/999/stock",
                json={"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "IN", "quantity": 5},
                headers={"Authorization": "Bearer token"},
            )
    assert resp.status_code == 404
    body = resp.get_json()
    assert body == {"error": "Product not found", "movement_id": "12345678-1234-4234-8234-123456789abc"}


def test_admin_product_cache_failure_does_not_log_sensitive_data(capsys, caplog):
    from src.controllers.admin_products_controller import admin_create_product

    secret = "synthetic-private-cache-detail"
    product_name = "synthetic-private-product-name"
    token = "synthetic-private-token"
    with app.test_request_context("/admin/products", method="POST", json={"name": product_name, "price": 10, "quantity": 1},
                                  headers={"Authorization": f"Bearer {token}"}), \
            patch("src.controllers.admin_products_controller.admin_create_product_service", return_value={"bgg_id": 1, "name": product_name}), \
            patch("builtins.open", side_effect=OSError(secret)):
        response, status = admin_create_product.__wrapped__()
    assert status == 201
    assert response.get_json()["bgg_id"] == 1
    captured = capsys.readouterr()
    assert all(value not in captured.out + captured.err + caplog.text for value in (secret, product_name, token))


def test_admin_product_cache_keeps_product_lookup_entry():
    import json
    from unittest.mock import mock_open
    from src.controllers.admin_products_controller import admin_create_product

    cache = mock_open()
    with app.test_request_context("/admin/products", method="POST", json={"name": "Game", "price": 10, "quantity": 1}), \
            patch("src.controllers.admin_products_controller.admin_create_product_service", return_value={"bgg_id": 1, "name": "Game"}), \
            patch("builtins.open", cache):
        _response, status = admin_create_product.__wrapped__()
    assert status == 201
    cache.assert_called_once_with("/tmp/bff-created-products.log", "a", encoding="utf-8")
    record = json.loads(cache().write.call_args.args[0])
    assert record["bgg_id"] == 1 and record["name"] == "Game"


@pytest.mark.parametrize(
    ("controller", "service", "path", "payload", "arguments"),
    [
        ("admin_create_product", "admin_create_product_service", "/admin/products", {"name": "Game", "price": 10, "quantity": 1}, ()),
        ("admin_update_product", "admin_update_product_service", "/admin/products/1", {"name": "Game"}, ("1",)),
        ("_admin_adjust_variant_stock", "adjust_product_stock_service", "/api/v1/admin/products/1/stock", {"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "IN", "quantity": 1}, ("1",)),
    ],
)
def test_admin_product_service_value_error_is_sanitized(controller, service, path, payload, arguments, capsys, caplog):
    from src.controllers import admin_products_controller

    secret = "synthetic-private-upstream-detail"
    with app.test_request_context(path, method="POST", json=payload), \
            patch.object(admin_products_controller, service, side_effect=ValueError(secret)):
        response, status = getattr(admin_products_controller, controller).__wrapped__(*arguments)
    captured = capsys.readouterr()
    assert status == 502
    assert secret not in response.get_data(as_text=True) + captured.out + captured.err + caplog.text


@pytest.mark.parametrize(
    ("controller", "path", "payload", "arguments", "message"),
    [
        ("admin_create_product", "/admin/products", {}, (), "name is required"),
        ("admin_update_product", "/admin/products/1", {}, ("1",), "at least one field must be provided"),
        ("_admin_adjust_variant_stock", "/api/v1/admin/products/1/stock", {"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "IN", "quantity": -1}, ("1",), "quantity must be a positive 32-bit integer"),
    ],
)
def test_admin_product_validation_errors_remain_client_errors(controller, path, payload, arguments, message):
    from src.controllers import admin_products_controller

    with app.test_request_context(path, method="POST", json=payload):
        response, status = getattr(admin_products_controller, controller).__wrapped__(*arguments)
    assert status == 400
    assert response.get_json()["error"] == message


def test_admin_product_user_error_mapping_in_controller():
    from src.controllers.admin_products_controller import admin_create_product
    from src.proxy import UpstreamError

    with app.test_request_context("/admin/products", method="POST", json={"name": "Game", "price": 10, "quantity": 1}), \
            patch("src.controllers.admin_products_controller.admin_create_product_service", side_effect=UpstreamError("Invalid name", "INVALID_NAME", field="name", user_error=True)):
        response, status = admin_create_product.__wrapped__()
    assert status == 400
    assert response.get_json()["errors"][0]["code"] == "INVALID_NAME"
