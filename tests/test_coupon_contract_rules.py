from pathlib import Path

import yaml


OPENAPI = Path(__file__).resolve().parents[1] / "specs" / "openapi.yaml"


def test_admin_coupon_contract_exposes_only_list_create_and_partial_update():
    spec = yaml.safe_load(OPENAPI.read_text())
    paths = spec["paths"]
    collection = paths["/api/v1/admin/coupons"]
    item = paths["/api/v1/admin/coupons/{coupon_id}"]

    assert set(collection) == {"get", "post"}
    assert set(item) == {"patch"}
    assert item["patch"]["parameters"][0]["schema"] == {
        "type": "integer",
        "minimum": 1,
    }
    for operation in (collection["get"], collection["post"], item["patch"]):
        assert operation["security"] == [{"BearerAuth": []}]
        assert {"401", "403", "502"} <= set(operation["responses"])
        assert "active staff or superuser" in operation["description"].lower()

    create = spec["components"]["schemas"]["AdminCreateCouponRequest"]
    update = spec["components"]["schemas"]["AdminUpdateCouponRequest"]
    coupon = spec["components"]["schemas"]["AdminCoupon"]
    fields = spec["components"]["schemas"]["AdminCouponRequestFields"]["properties"]
    assert set(create["allOf"][1]["required"]) == {
        "code", "discount_percent", "remaining", "active",
    }
    assert set(update["properties"]) == {
        "discount_percent", "remaining", "active", "starts_at", "ends_at",
    }
    assert "code" not in update["properties"]
    assert coupon["properties"]["id"]["type"] == "integer"
    assert coupon["properties"]["discount_percent"]["type"] == "number"
    assert coupon["properties"]["remaining"]["minimum"] == 0
    assert coupon["properties"]["discount_percent"]["minimum"] == 0
    assert coupon["properties"]["discount_percent"]["maximum"] == 50
    assert coupon["required"] == [
        "id", "code", "discount_percent", "remaining", "active",
        "starts_at", "ends_at", "created_at",
    ]
    assert coupon["properties"]["id"]["type"] == "integer"
    assert fields["code"]["maxLength"] == 64
    assert "exact-case" in fields["code"]["description"].lower()
    assert "inclusive" in fields["starts_at"]["description"].lower()
    assert "exclusive" in fields["ends_at"]["description"].lower()
    assert collection["post"]["responses"]["409"]["$ref"].endswith("/AdminConflict")
    assert item["patch"]["responses"]["404"]["$ref"].endswith("/AdminNotFound")
    assert spec["components"]["responses"]["AdminConflict"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/AdminFieldErrorResponse")
    assert collection["post"]["responses"]["502"]["$ref"].endswith(
        "/AdminCouponFailure"
    )
    for operation in (collection["post"], item["patch"]):
        assert "atomic" in operation["description"].lower()
        assert "audit" in operation["description"].lower()


def test_coupon_contract_uses_approved_rounding_and_authentication_rules():
    spec = yaml.safe_load(OPENAPI.read_text())
    preview = spec["paths"]["/api/v1/cart/coupons/preview"]["post"]
    description = preview["description"].lower()

    assert preview["security"] == [{"BearerAuth": []}]
    assert "round each total upward once" in description
    assert "ties favor the store promotion" in description
    assert "truncated" not in description
    assert "401" in preview["responses"]
    assert "404" in preview["responses"]


def test_current_cart_preview_route_forwards_authenticated_code_without_cart_id():
    from unittest.mock import patch

    from app import app

    client = app.test_client()
    with patch("src.controllers.admin_coupons_controller.preview_coupon_service",
        return_value={
            "valid": True,
            "coupon_code": "SAVE10",
            "discount_amount": 10,
            "new_total": 90,
            "reason": None,
        },
    ) as preview:
        response = client.post(
            "/api/v1/cart/coupons/preview",
            json={"coupon_code": "SAVE10"},
            headers={"Authorization": "Bearer buyer-token"},
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    preview.assert_called_once_with("SAVE10", "Bearer buyer-token")


def test_current_cart_preview_requires_authentication_and_maps_missing_coupon():
    from unittest.mock import patch

    from app import app
    from src.proxy import UpstreamError

    client = app.test_client()
    anonymous = client.post(
        "/api/v1/cart/coupons/preview", json={"coupon_code": "MISSING"}
    )
    assert anonymous.status_code == 401

    with patch(
        "src.controllers.admin_coupons_controller.preview_coupon_service",
        side_effect=UpstreamError("Coupon not found.", "COUPON_NOT_FOUND"),
    ):
        missing = client.post(
            "/api/v1/cart/coupons/preview",
            json={"coupon_code": "MISSING"},
            headers={"Authorization": "Bearer buyer-token"},
        )
    assert missing.status_code == 404
    assert missing.get_json()["errors"][0]["code"] == "COUPON_NOT_FOUND"
    assert "detail" not in missing.get_json()


def test_checkout_service_forwards_coupon_and_existing_op_key():
    from unittest.mock import patch

    from app import app

    with patch(
        "src.proxy.checkout",
        return_value={"order": {"id": "order-1"}, "init_point": "https://pay.test"},
    ) as checkout:
        response = app.test_client().post(
            "/api/v1/checkout",
            json={"shipping_mode": "pickup", "coupon_code": "SAVE10"},
            headers={
                "Authorization": "Bearer buyer-token",
                "X-Op-Key": "operation-key",
            },
        )

    assert response.status_code == 200
    checkout.assert_called_once_with(
        "pickup",
        None,
        "Bearer buyer-token",
        coupon_code="SAVE10",
        checkout_key="operation-key",
    )


def test_checkout_with_coupon_requires_operation_key():
    from unittest.mock import patch

    from app import app

    with patch("src.proxy.checkout") as checkout:
        response = app.test_client().post(
            "/api/v1/checkout",
            json={"shipping_mode": "pickup", "coupon_code": "SAVE10"},
            headers={"Authorization": "******"},
        )

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "INVALID"
    checkout.assert_not_called()


def test_checkout_contract_reuses_op_key_for_coupon_retry_identity():
    spec = yaml.safe_load(OPENAPI.read_text())
    checkout = spec["paths"]["/api/v1/checkout"]["post"]
    description = checkout["description"].lower()

    assert "x-op-key" in description
    assert "idempotency" in description
    assert checkout["security"] == [{"BearerAuth": []}]
    op_key = next(
        parameter
        for parameter in checkout["parameters"]
        if parameter["name"] == "X-Op-Key"
    )
    assert op_key["in"] == "header"
    assert op_key["required"] is False
    assert "required when coupon_code" in op_key["description"].lower()
    assert "reconciliation" in checkout["responses"]["409"]["description"].lower()
    response_schema = spec["components"]["schemas"]["CouponPreviewResponse"]
    assert {"valid", "coupon_code", "discount_amount", "new_total"} <= set(
        response_schema["required"]
    )
    preview_response = response_schema["properties"]
    assert preview_response["coupon_code"].get("nullable") is not True
    assert preview_response["discount_amount"].get("nullable") is not True
    assert preview_response["new_total"].get("nullable") is not True


def test_proxy_maps_current_cart_preview_and_forwards_checkout_key():
    from unittest.mock import patch

    from src.proxy import checkout, preview_coupon

    with patch(
        "src.proxy._graphql_request",
        return_value={
            "data": {
                "previewCoupon": {
                    "valid": True,
                    "couponCode": "SAVE10",
                    "discountAmount": 10,
                    "newTotal": 90,
                    "reason": None,
                }
            }
        },
    ) as graphql:
        preview = preview_coupon("SAVE10", "Bearer buyer-token")
    assert preview == {
        "valid": True,
        "coupon_code": "SAVE10",
        "discount_amount": 10,
        "new_total": 90,
        "reason": None,
    }
    graphql.assert_called_once()
    assert graphql.call_args.args[1] == {"code": "SAVE10"}
    assert graphql.call_args.args[2] == "Bearer buyer-token"

    with patch("src.proxy._graphql_request", return_value={}) as graphql, patch(
        "src.proxy._order_payload",
        return_value={"order": {"id": "order-1"}, "init_point": "https://pay.test"},
    ):
        checkout(
            "pickup", None, "Bearer buyer-token",
            coupon_code="SAVE10", checkout_key="operation-key",
        )
    variables = graphql.call_args.args[1]
    assert variables["couponCode"] == "SAVE10"
    assert variables["checkoutKey"] == "operation-key"
