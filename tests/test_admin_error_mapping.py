from unittest.mock import patch

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
