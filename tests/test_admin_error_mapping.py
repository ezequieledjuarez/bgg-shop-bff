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
            resp = client.post("/admin/products", json=valid_payload, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "errors" in body and isinstance(body["errors"], list)
    first = body["errors"][0]
    assert first["field"] == "name"
    assert first["code"] == "INVALID_NAME"


def test_adjust_stock_maps_user_error_to_400_with_field():
    client = app.test_client()

    def raise_upstream(product_id, variant_id, new_stock):
        from src.proxy import UpstreamError

        raise UpstreamError("Variant not found", "VARIANT_NOT_FOUND", field="variant_id", user_error=True)

    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_products_controller.adjust_variant_stock_service", side_effect=raise_upstream):
            resp = client.post(
                "/admin/products/1/variants/999/adjust-stock",
                json={"new_stock": 5},
                headers={"Authorization": "Bearer token"},
            )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["errors"][0]["code"] == "VARIANT_NOT_FOUND"


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
        ("admin_adjust_variant_stock", "adjust_variant_stock_service", "/admin/products/1/variants/2/adjust-stock", {"new_stock": 1}, ("1", "2")),
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
        ("admin_adjust_variant_stock", "/admin/products/1/variants/2/adjust-stock", {"new_stock": -1}, ("1", "2"), "new_stock must be greater than or equal to 0"),
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
