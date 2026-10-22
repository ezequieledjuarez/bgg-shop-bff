from unittest.mock import patch

from app import app


def test_coupons_apply_requires_auth():
    client = app.test_client()
    resp = client.post("/admin/coupons/SUMMER/apply", json={})
    assert resp.status_code == 401


def test_coupons_apply_preview_success():
    client = app.test_client()
    payload = {"cart_id": "cart-123"}
    with patch("src.proxy.check_admin", return_value=True):
        with patch(
            "src.controllers.admin_coupons_controller.admin_apply_coupon_preview_service",
            return_value={"valid": True, "discountAmount": 5.0, "newTotal": 45.0},
        ):
            resp = client.post(
                "/admin/coupons/SUMMER/apply", json=payload, headers={"Authorization": "Bearer token"}
            )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is True
    assert body["discountAmount"] == 5.0


def test_coupons_apply_user_error_maps_400():
    client = app.test_client()

    def raise_upstream(code, **payload):
        from src.proxy import UpstreamError

        raise UpstreamError("Invalid coupon", "INVALID_COUPON", field="code", user_error=True)

    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_coupons_controller.admin_apply_coupon_preview_service", side_effect=raise_upstream):
            resp = client.post(
                "/admin/coupons/SUMMER/apply", json={"cart_id": "cart-123"}, headers={"Authorization": "Bearer token"}
            )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "errors" in body and isinstance(body["errors"], list)
    first = body["errors"][0]
    assert first["code"] == "INVALID_COUPON"
