from unittest.mock import patch
import pytest

from app import app
from src.dtos.promotions import PromotionCreateDto, PromotionUpdateDto


@pytest.mark.parametrize("dto", [
    PromotionCreateDto(name="Sale", discount_percent=50.01, active=True),
    PromotionUpdateDto(name=None, discount_percent=50.01, active=None),
    PromotionCreateDto(name="Sale", discount_percent=float("nan"), active=True),
    PromotionUpdateDto(name=None, discount_percent=float("nan"), active=None),
])
def test_promotion_discount_above_limit_or_nonfinite_is_rejected(dto):
    with pytest.raises(ValueError):
        dto.validate()


@pytest.mark.parametrize("dto", [
    PromotionCreateDto(name="Sale", discount_percent=50, active=True),
    PromotionUpdateDto(name=None, discount_percent=50, active=None),
])
def test_promotion_discount_at_limit_is_accepted(dto):
    assert dto.validate()["discount_percent"] == 50


@pytest.mark.parametrize("payload", [
    {"name": "Sale", "discount_percent": "20", "active": True},
    {"name": "Sale", "discount_percent": True, "active": True},
    {"name": "Sale", "discount_percent": 20, "active": "false"},
    {"name": "Sale", "discount_percent": 20, "active": 0},
    {"name": "Sale", "discount_percent": 20, "active": None},
    {"name": "Sale", "discount_percent": 20, "unexpected": "value"},
])
def test_promotion_create_rejects_values_outside_openapi_contract(payload):
    with pytest.raises(ValueError):
        PromotionCreateDto.from_payload(payload).validate()


@pytest.mark.parametrize("payload", [
    {"discount_percent": "20"},
    {"discount_percent": True},
    {"discount_percent": None},
    {"active": "false"},
    {"active": 0},
    {"active": None},
    {"name": "Sale", "unexpected": "value"},
])
def test_promotion_update_rejects_values_outside_openapi_contract(payload):
    with pytest.raises(ValueError):
        PromotionUpdateDto.from_payload(payload).validate()


@pytest.mark.parametrize("active", [True, False])
def test_promotion_boolean_values_remain_unchanged(active):
    created = PromotionCreateDto.from_payload({"name": "Sale", "discount_percent": 20, "active": active}).validate()
    updated = PromotionUpdateDto.from_payload({"active": active}).validate()
    assert created["active"] is active
    assert updated["active"] is active


def test_promotion_create_preserves_omitted_active_default():
    assert PromotionCreateDto.from_payload({"name": "Sale", "discount_percent": 20}).validate()["active"] is False


@pytest.mark.parametrize(("dto_type", "payload", "expected"), [
    (PromotionCreateDto, {"name": "Sale", "discount_percent": 20, "product_bgg_id": 42},
     {"name": "Sale", "discount_percent": 20.0, "active": False, "product_bgg_id": 42}),
    (PromotionCreateDto, {"name": "Sale", "discount_percent": 20, "product_bgg_id": None},
     {"name": "Sale", "discount_percent": 20.0, "active": False, "product_bgg_id": None}),
    (PromotionUpdateDto, {"product_bgg_id": 42}, {"product_bgg_id": 42}),
    (PromotionUpdateDto, {"product_bgg_id": None}, {"product_bgg_id": None}),
])
def test_promotion_dtos_accept_optional_nullable_product_bgg_id(dto_type, payload, expected):
    assert dto_type.from_payload(payload).validate() == expected


@pytest.mark.parametrize(("dto_type", "payload"), [
    (PromotionCreateDto, {"name": "Sale", "discount_percent": 20, "product_bgg_id": 0}),
    (PromotionCreateDto, {"name": "Sale", "discount_percent": 20, "product_bgg_id": True}),
    (PromotionUpdateDto, {"product_bgg_id": "42"}),
])
def test_promotion_dtos_reject_invalid_product_bgg_id(dto_type, payload):
    with pytest.raises(ValueError):
        dto_type.from_payload(payload).validate()


@pytest.mark.parametrize(("method", "path", "payload", "root", "expected_input"), [
    ("POST", "/api/v1/admin/promotions",
     {"name": "Sale", "discount_percent": 20, "product_bgg_id": 42}, "createPromotion",
     {"name": "Sale", "discountPercent": 20.0, "active": False, "productBggId": 42}),
    ("POST", "/api/v1/admin/promotions",
     {"name": "Sale", "discount_percent": 20, "product_bgg_id": None}, "createPromotion",
     {"name": "Sale", "discountPercent": 20.0, "active": False, "productBggId": None}),
    ("POST", "/api/v1/admin/promotions",
     {"name": "Sale", "discount_percent": 20}, "createPromotion",
     {"name": "Sale", "discountPercent": 20.0, "active": False}),
    ("PUT", "/api/v1/admin/promotions/1",
     {"product_bgg_id": 42}, "updatePromotion", {"productBggId": 42}),
    ("PUT", "/api/v1/admin/promotions/1",
     {"product_bgg_id": None}, "updatePromotion", {"productBggId": None}),
])
def test_promotion_product_bgg_id_maps_to_core_camel_case(method, path, payload, root, expected_input):
    response_payload = {"data": {root: {"promotion": {"id": "1", "name": "Sale"}, "userErrors": []}}}
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=response_payload) as graphql:
        response = app.test_client().open(
            path, method=method, json=payload, headers={"Authorization": "******"}
        )
    assert response.status_code == (201 if method == "POST" else 200)
    variables = graphql.call_args.args[1]
    input_payload = variables["input"]
    assert input_payload == expected_input


@pytest.mark.parametrize("method,path,service,payload", [
    ("POST", "/api/v1/admin/promotions", "admin_create_promotion_service", {"name": "Sale", "discount_percent": 20, "active": "false"}),
    ("POST", "/api/v1/admin/promotions", "admin_create_promotion_service", {"name": "Sale", "discount_percent": "20"}),
    ("PUT", "/api/v1/admin/promotions/1", "admin_update_promotion_service", {"active": 0}),
    ("PUT", "/api/v1/admin/promotions/1", "admin_update_promotion_service", {"name": "Sale", "unexpected": "value"}),
])
def test_promotion_invalid_contract_input_is_rejected_before_service(method, path, service, payload):
    with patch("src.proxy.check_admin", return_value=True), \
            patch(f"src.controllers.admin_promotions_controller.{service}") as upstream:
        response = app.test_client().open(path, method=method, json=payload, headers={"Authorization": "Bearer token"})
    assert response.status_code == 400
    upstream.assert_not_called()


def test_promotion_update_maps_discount_to_core_input():
    response_payload = {"data": {"updatePromotion": {"promotion": {"id": "1", "name": "Sale"}, "userErrors": []}}}
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=response_payload) as graphql:
        response = app.test_client().put(
            "/api/v1/admin/promotions/1", json={"discount_percent": 20},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    assert graphql.call_args.args[1] == {"id": "1", "input": {"discountPercent": 20.0}}
    assert graphql.call_args.args[2] == "Bearer token"


def test_promotions_list_requires_auth():
    client = app.test_client()
    resp = client.get("/api/v1/admin/promotions")
    assert resp.status_code == 401


def test_promotions_list_maps_core_discount_field():
    payload = {"data": {"promotions": [{"id": "1", "name": "Sale", "discountPercent": 20, "active": False, "productBggId": None}]}}
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=payload) as graphql:
        response = app.test_client().get("/api/v1/admin/promotions", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    assert response.get_json() == [
        {"id": "1", "name": "Sale", "discount_percent": 20, "active": False, "product_bgg_id": None}
    ]
    assert "discountPercent: discountPct" in graphql.call_args.args[0]
    assert "productBggId" in graphql.call_args.args[0]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer synthetic"}])
def test_available_coupons_public_endpoint_maps_core_response(headers):
    payload = {"data": {"availableCoupons": [{"code": "SALE", "startsAt": "2026-11-01T00:00:00+00:00", "endsAt": "2026-11-30T00:00:00+00:00"}]}}
    with patch("src.proxy._graphql_request", return_value=payload) as graphql:
        response = app.test_client().get("/api/v1/coupons", headers=headers)
    assert response.status_code == 200
    assert response.get_json() == [{"code": "SALE", "starts_at": "2026-11-01T00:00:00+00:00", "ends_at": "2026-11-30T00:00:00+00:00"}]
    assert response.headers["Cache-Control"] == "no-store"
    assert "availableCoupons" in graphql.call_args.args[0]


@pytest.mark.parametrize("payload", [
    {"errors": [{"message": "private upstream detail"}]},
    {"data": {"availableCoupons": [None]}},
    {"data": {"availableCoupons": [{"code": "SALE", "startsAt": "bad", "endsAt": "bad"}]}},
])
def test_available_coupons_hides_invalid_upstream_details(payload):
    with patch("src.proxy._graphql_request", return_value=payload):
        response = app.test_client().get("/api/v1/coupons")
    assert response.status_code == 502
    assert b"private upstream detail" not in response.data


def test_promotions_create_validation_and_success():
    client = app.test_client()
    payload = {"name": "Spring Sale", "discount_percent": 20, "active": True}
    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.controllers.admin_promotions_controller.admin_create_promotion_service", return_value={"id": "1", "name": "Spring Sale"}):
            resp = client.post("/api/v1/admin/promotions", json=payload, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 201
    assert resp.get_json()["name"] == "Spring Sale"


def test_promotion_user_errors_use_static_messages_without_upstream_detail():
    from src.proxy import UpstreamError

    leak = "psycopg2 Traceback http://core:8000 password=hunter2"
    cases = [("INVALID", ["discount_pct"], 400), ("UNAUTHENTICATED", None, 401), ("FORBIDDEN", None, 403), ("NOT_FOUND", None, 404)]
    for code, field, status in cases:
        with patch("src.proxy.check_admin", return_value=True), patch(
            "src.controllers.admin_promotions_controller.admin_update_promotion_service",
            side_effect=UpstreamError(leak, code, field, user_error=True),
        ):
            resp = app.test_client().put(
                "/api/v1/admin/promotions/1", json={"active": False}, headers={"Authorization": "Bearer t"}
            )
        assert resp.status_code == status
        text = resp.get_data(as_text=True)
        assert "Traceback" not in text and "hunter2" not in text and "core:8000" not in text


def test_promotion_non_user_upstream_error_is_static_502():
    from src.proxy import UpstreamError

    with patch("src.proxy.check_admin", return_value=True), patch(
        "src.controllers.admin_promotions_controller.admin_create_promotion_service",
        side_effect=UpstreamError("Traceback password=hunter2", "SERVER_ERROR", user_error=True),
    ):
        resp = app.test_client().post(
            "/api/v1/admin/promotions",
            json={"name": "Promo", "discount_pct": 10, "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-02-01T00:00:00Z"},
            headers={"Authorization": "Bearer t"},
        )
    assert resp.status_code in (400, 502)
    assert "hunter2" not in resp.get_data(as_text=True)


@pytest.mark.parametrize(("method", "path", "payload", "root"), [
    ("POST", "/api/v1/admin/promotions", {"name": "Sale", "discount_percent": 20, "product_bgg_id": None}, "createPromotion"),
    ("PUT", "/api/v1/admin/promotions/1", {"discount_percent": 20}, "updatePromotion"),
])
def test_promotion_mutations_forward_validated_op_key_to_upstream(method, path, payload, root):
    from flask import g

    key = "synthetic-op-key"
    response_payload = {"data": {root: {"promotion": {"id": "1", "name": "Sale"}, "userErrors": []}}}
    with patch("app._opkey_before_request", side_effect=lambda: setattr(g, "op_session_valid", True)), \
            patch("src.proxy._graphql_request", return_value=response_payload) as graphql:
        response = app.test_client().open(path, method=method, json=payload, headers={"X-Op-Key": key})
    assert response.status_code == (201 if method == "POST" else 200)
    assert graphql.call_args.args[2] is None
    assert graphql.call_args.kwargs == {"op_key": key}
    assert "_op_key" not in graphql.call_args.args[1]["input"]
    assert key not in response.get_data(as_text=True)
