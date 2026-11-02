from unittest.mock import patch

import pytest
from flask import g

from app import app
from src import services


def test_coupons_apply_requires_auth():
    client = app.test_client()
    resp = client.post("/api/v1/admin/coupons/SUMMER/apply", json={})
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
                "/api/v1/admin/coupons/SUMMER/apply", json=payload, headers={"Authorization": "Bearer token"}
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
                "/api/v1/admin/coupons/SUMMER/apply", json={"cart_id": "cart-123"}, headers={"Authorization": "Bearer token"}
            )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "errors" in body and isinstance(body["errors"], list)
    first = body["errors"][0]
    assert first["code"] == "INVALID_COUPON"


def test_coupons_apply_upstream_failure_is_sanitized():
    from src.proxy import UpstreamError

    secret = "https://internal.example/trace token=synthetic-secret"
    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_apply_coupon_preview_service",
        side_effect=UpstreamError(secret),
    ):
        response = app.test_client().post(
            "/api/v1/admin/coupons/SUMMER/apply",
            json={"cart_id": "cart-123"},
            headers={"Authorization": "******"},
        )

    assert response.status_code == 502
    assert response.get_json() == {"error": "upstream GraphQL request failed"}
    assert secret not in response.get_data(as_text=True)


def test_admin_coupon_routes_require_staff_authentication():
    client = app.test_client()
    assert client.get("/api/v1/admin/coupons").status_code == 401
    assert client.post("/api/v1/admin/coupons", json={}).status_code == 401
    assert client.patch("/api/v1/admin/coupons/1", json={"active": False}).status_code == 401


def test_validated_opkey_is_forwarded_through_coupon_controller_and_service():
    key = "synthetic-op-key"
    with patch("app._opkey_before_request", side_effect=lambda: setattr(g, "op_session_valid", True)), \
            patch("src.controllers.admin_coupons_controller.admin_list_coupons_service", return_value=[]) as listing:
        response = app.test_client().get("/api/v1/admin/coupons", headers={"X-Op-Key": key})
    assert response.status_code == 200
    listing.assert_called_once_with(None, key)

    values = {"code": "SAVE10", "discount_percent": 10, "remaining": 3, "active": True}
    with patch("app._opkey_before_request", side_effect=lambda: setattr(g, "op_session_valid", True)), \
            patch("src.controllers.admin_coupons_controller.admin_create_coupon_service",
                  return_value={"id": 4}) as create:
        response = app.test_client().post(
            "/api/v1/admin/coupons", json=values, headers={"X-Op-Key": key}
        )
    assert response.status_code == 201
    create.assert_called_once_with({**values, "_auth_token": None, "_op_key": key})

    with patch("src.services.proxy.list_admin_coupons", return_value=[]) as upstream:
        services.admin_list_coupons(None, key)
    upstream.assert_called_once_with(None, op_key=key)

    with patch("src.services.proxy.create_admin_coupon", return_value={}) as upstream:
        services.admin_create_coupon({**values, "_auth_token": None, "_op_key": key})
    upstream.assert_called_once_with(values, None, op_key=key)


def test_admin_coupon_list_returns_flattened_values_without_caching():
    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_list_coupons_service",
        return_value=[
            {
                "id": 4,
                "code": "SAVE10",
                "discount_percent": 10,
                "remaining": 3,
                "active": True,
                "starts_at": None,
                "ends_at": None,
                "created_at": "2026-11-02T00:00:00+00:00",
            }
        ],
    ):
        response = app.test_client().get(
            "/api/v1/admin/coupons", headers={"Authorization": "Bearer admin"}
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()[0]["discount_percent"] == 10


def test_admin_coupon_list_upstream_failure_is_sanitized_and_not_cached():
    from src.proxy import UpstreamError

    secret = "https://internal.example/debug token=synthetic-secret"
    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_list_coupons_service",
        side_effect=UpstreamError(secret),
    ):
        response = app.test_client().get(
            "/api/v1/admin/coupons", headers={"Authorization": "******"}
        )

    assert response.status_code == 502
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"error": "upstream GraphQL request failed"}
    assert secret not in response.get_data(as_text=True)


def test_admin_coupon_create_passes_validated_fields_and_never_returns_auth():
    values = {
        "code": "SAVE10",
        "discount_percent": 10,
        "remaining": 3,
        "active": True,
        "starts_at": None,
        "ends_at": None,
    }
    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_create_coupon_service",
        return_value={"id": 4, **values, "created_at": "2026-11-02T00:00:00+00:00"},
    ) as create:
        response = app.test_client().post(
            "/api/v1/admin/coupons",
            json=values,
            headers={"Authorization": "Bearer admin"},
        )

    assert response.status_code == 201
    create.assert_called_once_with({**values, "_auth_token": "Bearer admin"})
    assert "auth" not in response.get_data(as_text=True).lower()
    assert response.get_json()["id"] == 4


def test_admin_coupon_update_is_partial_and_code_is_not_mutable():
    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_update_coupon_service",
        return_value={"id": 4, "active": False},
    ) as update:
        response = app.test_client().patch(
            "/api/v1/admin/coupons/4",
            json={"active": False},
            headers={"Authorization": "Bearer admin"},
        )

    assert response.status_code == 200
    update.assert_called_once_with(4, {"active": False, "_auth_token": "Bearer admin"})

    with patch("src.proxy.check_admin", return_value=True):
        immutable = app.test_client().patch(
        "/api/v1/admin/coupons/4",
        json={"code": "OTHER"},
        headers={"Authorization": "Bearer admin"},
    )
    assert immutable.status_code == 400


def test_admin_coupon_duplicate_code_maps_to_conflict_without_upstream_details():
    from src.proxy import UpstreamError

    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_create_coupon_service",
        side_effect=UpstreamError("A coupon with this code already exists.", "CODE_EXISTS", user_error=True),
    ):
        response = app.test_client().post(
            "/api/v1/admin/coupons",
            json={
                "code": "SAVE10",
                "discount_percent": 10,
                "remaining": 3,
                "active": True,
            },
            headers={"Authorization": "Bearer admin"},
        )

    assert response.status_code == 409
    assert response.get_json()["errors"][0]["code"] == "CODE_EXISTS"
    assert "upstream" not in response.get_data(as_text=True).lower()


@pytest.mark.parametrize(
    ("code", "expected_status", "expected_message"),
    [
        ("UNAUTHENTICATED", 401, "Authentication is required."),
        ("FORBIDDEN", 403, "Administrative permission is required."),
        ("NOT_FOUND", 404, "Coupon not found."),
    ],
)
def test_admin_coupon_update_maps_known_upstream_errors_to_static_responses(
    code, expected_status, expected_message
):
    from src.proxy import UpstreamError

    secret = "https://internal.example/trace synthetic-private-field"
    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_update_coupon_service",
        side_effect=UpstreamError(
            secret,
            code,
            field=["discountPercent", "synthetic-private-field"],
            user_error=True,
        ),
    ):
        response = app.test_client().patch(
            "/api/v1/admin/coupons/4",
            json={"active": False},
            headers={"Authorization": "******"},
        )

    assert response.status_code == expected_status
    assert response.get_json() == {"error": expected_message}
    assert secret not in response.get_data(as_text=True)
    assert "synthetic-private-field" not in response.get_data(as_text=True)


def test_admin_coupon_proxy_maps_flattened_core_shape_and_forwards_only_contract_fields():
    from src.services import admin_create_coupon

    core_coupon = {
        "id": 4,
        "code": "SAVE10",
        "discountPercent": 10,
        "remaining": 3,
        "active": True,
        "startsAt": None,
        "endsAt": None,
        "createdAt": "2026-11-02T00:00:00+00:00",
    }
    request_values = {
        "code": "SAVE10",
        "discount_percent": 10,
        "remaining": 3,
        "active": True,
    }
    with patch(
        "src.proxy._graphql_request",
        return_value={
            "data": {
                "createAdminCoupon": {"coupon": core_coupon, "userErrors": []}
            }
        },
    ) as graphql:
        result = admin_create_coupon(
            {**request_values, "_auth_token": "Bearer admin"}
        )

    assert result == {
        "id": 4,
        "code": "SAVE10",
        "discount_percent": 10,
        "remaining": 3,
        "active": True,
        "starts_at": None,
        "ends_at": None,
        "created_at": "2026-11-02T00:00:00+00:00",
    }
    assert graphql.call_args.args[1] == {
        "input": {
            "code": "SAVE10",
            "discountPercent": 10.0,
            "remaining": 3,
            "active": True,
        }
    }
    assert graphql.call_args.args[2] == "Bearer admin"


def test_admin_coupon_proxy_reads_and_partially_updates_numeric_records():
    from src.proxy import list_admin_coupons, update_admin_coupon

    core_coupon = {
        "id": 9,
        "code": "SAVE10",
        "discountPercent": 0,
        "remaining": 0,
        "active": False,
        "startsAt": None,
        "endsAt": None,
        "createdAt": "2026-11-02T00:00:00+00:00",
    }
    with patch(
        "src.proxy._graphql_request",
        return_value={"data": {"adminCoupons": [core_coupon]}},
    ) as graphql:
        listed = list_admin_coupons("Bearer admin")
    assert listed[0]["id"] == 9
    assert listed[0]["discount_percent"] == 0
    assert graphql.call_args.args[2] == "Bearer admin"

    with patch(
        "src.proxy._graphql_request",
        return_value={
            "data": {
                "updateAdminCoupon": {"coupon": core_coupon, "userErrors": []}
            }
        },
    ) as graphql:
        updated = update_admin_coupon(9, {"active": False, "ends_at": None}, "Bearer admin")
    assert updated["active"] is False
    assert graphql.call_args.args[1] == {
        "id": 9,
        "input": {"active": False, "endsAt": None},
    }


def test_coupon_dto_preserves_exact_codes_and_rejects_invalid_date_ranges():
    from src.dtos.coupons import AdminCouponCreateDto, AdminCouponUpdateDto

    valid = AdminCouponCreateDto.from_payload(
        {
            "code": "CaseSensitive",
            "discount_percent": 0,
            "remaining": 0,
            "active": False,
            "starts_at": "2026-11-01T00:00:00Z",
            "ends_at": "2026-11-02T00:00:00+00:00",
        }
    ).validate()
    assert valid["code"] == "CaseSensitive"
    assert valid["discount_percent"] == 0

    with pytest.raises(ValueError, match="earlier"):
        AdminCouponUpdateDto.from_payload(
            {
                "starts_at": "2026-11-02T00:00:00Z",
                "ends_at": "2026-11-01T00:00:00Z",
            }
        ).validate()
    with pytest.raises(ValueError, match="Unknown coupon field"):
        AdminCouponUpdateDto.from_payload({"code": "CHANGED"}).validate()


def test_admin_coupon_hides_untrusted_upstream_failure_details():
    from src.proxy import UpstreamError

    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_create_coupon_service",
        side_effect=UpstreamError(
            "https://internal.example/debug token=example-secret stacktrace",
        ),
    ):
        response = app.test_client().post(
            "/api/v1/admin/coupons",
            json={
                "code": "SAVE10",
                "discount_percent": 10,
                "remaining": 1,
                "active": True,
            },
            headers={"Authorization": "Bearer example-secret"},
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 502
    assert "internal.example" not in body
    assert "example-secret" not in body
    assert "stacktrace" not in body


def test_admin_coupon_core_audit_failure_is_not_reported_as_client_error():
    from src.proxy import UpstreamError

    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_create_coupon_service",
        side_effect=UpstreamError(
            "Could not create coupon.", "SERVER_ERROR", user_error=True
        ),
    ):
        response = app.test_client().post(
            "/api/v1/admin/coupons",
            json={
                "code": "SAVE10",
                "discount_percent": 10,
                "remaining": 1,
                "active": True,
            },
            headers={"Authorization": "Bearer admin"},
        )

    assert response.status_code == 502
    assert response.get_json() == {"error": "upstream GraphQL request failed"}


def test_admin_coupon_unknown_user_error_message_is_static():
    from src.proxy import UpstreamError

    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_coupons_controller.admin_update_coupon_service",
        side_effect=UpstreamError("Traceback http://core:8000 password=hunter2", "WEIRD", ["discountPercent"], user_error=True),
    ):
        resp = app.test_client().patch(
            "/api/v1/admin/coupons/1", json={"active": False}, headers={"Authorization": "Bearer t"}
        )
    assert resp.status_code == 400
    text = resp.get_data(as_text=True)
    assert "hunter2" not in text and "Traceback" not in text
    assert resp.get_json()["errors"][0]["field"] == "discount_percent"
