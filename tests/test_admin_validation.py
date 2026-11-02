from unittest.mock import patch
from uuid import UUID

import pytest
import requests

from app import app


@pytest.mark.parametrize("direction,before,applied,after", [("IN", 5, 3, 8), ("OUT", 5, 5, 0)])
def test_record_stock_movement_returns_applied_result(direction, before, applied, after):
    movement_id = "12345678-1234-4234-8234-123456789abc"
    quantity = 3 if direction == "IN" else 9
    result = {"data": {"adjustProductStock": {"movementId": movement_id, "status": "APPLIED", "requestedQuantity": quantity,
              "appliedQuantity": applied, "quantityBefore": before, "quantityAfter": after, "errors": []}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=result) as graphql:
        response = app.test_client().post("/api/v1/admin/products/42/stock", json={"movement_id": movement_id, "direction": direction, "quantity": quantity}, headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    expected = {"movement_id": movement_id, "status": "APPLIED", "requested_quantity": quantity,
                "applied_quantity": applied, "quantity_before": before, "quantity_after": after}
    if direction == "OUT":
        expected["warning"] = "Requested quantity exceeded available stock; stock is now zero."
    assert response.get_json() == expected
    assert graphql.call_args.args[1] == {"productId": "42", "movementId": movement_id, "direction": direction, "quantity": quantity}


def test_record_stock_movement_returns_in_progress():
    movement_id = "12345678-1234-4234-8234-123456789abc"
    result = {"data": {"adjustProductStock": {"movementId": movement_id, "status": "IN_PROGRESS", "requestedQuantity": None,
              "appliedQuantity": None, "quantityBefore": None, "quantityAfter": None, "errors": []}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=result):
        response = app.test_client().post("/api/v1/admin/products/42/stock", json={"movement_id": movement_id, "direction": "IN", "quantity": 3}, headers={"Authorization": "Bearer token"})
    assert response.status_code == 202
    assert response.get_json() == {"movement_id": movement_id, "status": "IN_PROGRESS"}


def test_record_stock_movement_conflict_is_sanitized():
    movement_id = "12345678-1234-4234-8234-123456789abc"
    result = {"data": {"adjustProductStock": {"movementId": movement_id, "status": None, "errors": [{"code": "IDEMPOTENCY_CONFLICT", "message": "private detail"}]}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=result):
        response = app.test_client().post("/api/v1/admin/products/42/stock", json={"movement_id": movement_id, "direction": "IN", "quantity": 3}, headers={"Authorization": "Bearer token"})
    assert response.status_code == 409
    assert response.get_json()["movement_id"] == movement_id
    assert "private detail" not in response.get_data(as_text=True)


def test_record_stock_movement_uncertain_error_suggests_refresh_and_status():
    from src.proxy import UpstreamError

    movement_id = "12345678-1234-4234-8234-123456789abc"
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", side_effect=UpstreamError("private transport detail")):
        response = app.test_client().post("/api/v1/admin/products/42/stock", json={"movement_id": movement_id, "direction": "IN", "quantity": 3}, headers={"Authorization": "Bearer token"})
    assert response.status_code == 502
    assert response.get_json()["movement_id"] == movement_id
    assert "refresh" in response.get_json()["error"].lower()
    assert "status" in response.get_json()["error"].lower()
    assert "private transport detail" not in response.get_data(as_text=True)


@pytest.mark.parametrize("admin,expected", [(None, 401), (False, 403)])
def test_record_stock_movement_auth_errors_include_uuid(admin, expected):
    payload = {"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "IN", "quantity": 3}
    with patch("src.proxy.check_admin", return_value=admin), patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().post("/api/v1/admin/products/42/stock", json=payload, headers={"Authorization": "Bearer token"})
    assert response.status_code == expected
    assert response.get_json()["movement_id"] == payload["movement_id"]
    graphql.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"movementId": "12345678-1234-4234-8234-123456789abd"},
    {"requestedQuantity": 4}, {"appliedQuantity": 4}, {"quantityBefore": True},
    {"quantityAfter": 7}, {"status": "UNKNOWN"},
    {"status": "IN_PROGRESS", "quantityAfter": 8},
    {"errors": [{"code": "NOT_FOUND"}]},
])
def test_record_stock_movement_rejects_inconsistent_core_response(changes):
    movement_id = "12345678-1234-4234-8234-123456789abc"
    result = {"movementId": movement_id, "status": "APPLIED", "requestedQuantity": 3,
              "appliedQuantity": 3, "quantityBefore": 5, "quantityAfter": 8, "errors": []}
    result.update(changes)
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value={"data": {"adjustProductStock": result}}):
        response = app.test_client().post("/api/v1/admin/products/42/stock", json={"movement_id": movement_id, "direction": "IN", "quantity": 3}, headers={"Authorization": "Bearer token"})
    assert response.status_code == 502
    assert response.get_json()["movement_id"] == movement_id


@pytest.mark.parametrize("payload", [
    {}, {"movement_id": "invalid", "direction": "IN", "quantity": 1},
    {"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "IN", "quantity": 0},
    {"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "OUT", "quantity": True},
    {"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "OTHER", "quantity": 1},
    {"new_stock": 1},
])
def test_record_stock_movement_rejects_invalid_request(payload):
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().post("/api/v1/admin/products/42/stock", json=payload, headers={"Authorization": "Bearer token"})
    assert response.status_code == 400
    graphql.assert_not_called()


@pytest.mark.parametrize("status", ["IN_PROGRESS", "APPLIED", "REJECTED"])
def test_stock_movement_status_returns_core_status(status):
    movement_id = "12345678-1234-4234-8234-123456789abc"
    result = {"data": {"adminStockMovementStatus": {"movementId": movement_id, "status": status, "userErrors": []}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=result) as graphql:
        response = app.test_client().get(f"/api/v1/admin/stock-movements/{movement_id}", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    assert response.get_json() == {"movement_id": movement_id, "status": status}
    assert response.headers["Cache-Control"] == "no-store"
    assert graphql.call_args.args[1] == {"movementId": movement_id}


@pytest.mark.parametrize("code,status", [("INVALID", 400), ("UNAUTHENTICATED", 401), ("FORBIDDEN", 403), ("NOT_FOUND", 404), ("SERVER_ERROR", 502)])
def test_stock_movement_status_sanitizes_core_errors(code, status):
    movement_id = "12345678-1234-4234-8234-123456789abc"
    result = {"data": {"adminStockMovementStatus": {"movementId": movement_id, "status": None, "userErrors": [{"code": code, "message": "private detail"}]}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=result):
        response = app.test_client().get(f"/api/v1/admin/stock-movements/{movement_id}", headers={"Authorization": "Bearer token"})
    assert response.status_code == status
    assert response.get_json()["movement_id"] == movement_id
    assert "private detail" not in response.get_data(as_text=True)


@pytest.mark.parametrize("admin,expected", [(None, 401), (False, 403)])
def test_stock_movement_status_auth_errors_include_uuid(admin, expected):
    movement_id = "12345678-1234-4234-8234-123456789abc"
    with patch("src.proxy.check_admin", return_value=admin), patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().get(f"/api/v1/admin/stock-movements/{movement_id}", headers={"Authorization": "Bearer token"})
    assert response.status_code == expected
    assert response.get_json()["movement_id"] == movement_id
    graphql.assert_not_called()


def test_stock_movement_status_rejects_invalid_uuid_before_core():
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().get("/api/v1/admin/stock-movements/invalid", headers={"Authorization": "Bearer token"})
    assert response.status_code == 400
    graphql.assert_not_called()


@pytest.mark.parametrize("result", [
    {}, {"errors": [{"message": "private detail"}]},
    {"data": {"adminStockMovementStatus": {"movementId": "12345678-1234-4234-8234-123456789abd", "status": "APPLIED", "userErrors": []}}},
    {"data": {"adminStockMovementStatus": {"movementId": "12345678-1234-4234-8234-123456789abc", "status": "UNKNOWN", "userErrors": []}}},
    {"data": {"adminStockMovementStatus": {"movementId": "12345678-1234-4234-8234-123456789abc", "status": None, "userErrors": ["private detail"]}}},
    {"data": {"adminStockMovementStatus": {"movementId": "12345678-1234-4234-8234-123456789abc", "status": "APPLIED", "userErrors": [{"code": "NOT_FOUND"}]}}},
])
def test_stock_movement_status_rejects_invalid_core_response(result):
    movement_id = "12345678-1234-4234-8234-123456789abc"
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=result):
        response = app.test_client().get(f"/api/v1/admin/stock-movements/{movement_id}", headers={"Authorization": "Bearer token"})
    assert response.status_code == 502
    assert response.get_json()["movement_id"] == movement_id
    assert "private detail" not in response.get_data(as_text=True)


@pytest.mark.parametrize("validation,expected", [({"valid": False}, 401), (None, 502)])
def test_stock_movement_status_rejects_invalid_opkey_or_validation_failure(validation, expected):
    movement_id = "12345678-1234-4234-8234-123456789abc"
    with patch("src.opkey_middleware.validate_op_key_with_core", return_value=validation), patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().get(f"/api/v1/admin/stock-movements/{movement_id}", headers={"X-Op-Key": "synthetic-key"})
    assert response.status_code == expected
    assert response.get_json()["movement_id"] == movement_id
    graphql.assert_not_called()


def test_stock_movement_status_sanitizes_transport_failure():
    movement_id = "12345678-1234-4234-8234-123456789abc"
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy.requests.post", side_effect=requests.ConnectionError("private upstream detail")):
        response = app.test_client().get(f"/api/v1/admin/stock-movements/{movement_id}", headers={"Authorization": "Bearer token"})
    assert response.status_code == 502
    assert response.get_json()["movement_id"] == movement_id
    assert "private upstream detail" not in response.get_data(as_text=True)


def test_stock_movement_status_delegates_opkey(monkeypatch):
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", "synthetic-internal-secret-0123456789-abcdef")
    movement_id = "12345678-1234-4234-8234-123456789abc"
    path = f"/api/v1/admin/stock-movements/{movement_id}"
    result = {"data": {"adminStockMovementStatus": {"movementId": movement_id, "status": "APPLIED", "userErrors": []}}}
    with patch("src.opkey_middleware.validate_op_key_with_core", return_value={"valid": True}) as validate, \
            patch("src.proxy.requests.post") as post:
        post.return_value.json.return_value = result
        response = app.test_client().get(path, headers={"X-Op-Key": "synthetic-key"})
    assert response.status_code == 200
    validate.assert_called_once_with("synthetic-key", path, "GET")
    assert post.call_args.kwargs["headers"]["X-Op-Path"] == path
    assert post.call_args.kwargs["headers"]["X-Op-Method"] == "GET"


def test_stock_movement_id_generation_requires_admin_and_is_not_cached():
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request") as graphql:
        client = app.test_client()
        first = client.post("/api/v1/admin/stock-movement-ids", headers={"Authorization": "Bearer token"})
        second = client.post("/api/v1/admin/stock-movement-ids", headers={"Authorization": "Bearer token"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert set(first.get_json()) == {"movement_id"}
    assert UUID(first.get_json()["movement_id"]).version == 4
    assert first.get_json()["movement_id"] != second.get_json()["movement_id"]
    assert first.headers["Cache-Control"] == "no-store"
    graphql.assert_not_called()


@pytest.mark.parametrize("headers,admin,expected", [
    ({}, None, 401),
    ({"Authorization": "Bearer invalid"}, None, 401),
    ({"Authorization": "Bearer non-admin"}, False, 403),
])
def test_stock_movement_id_generation_rejects_unauthorized(headers, admin, expected):
    with patch("src.proxy.check_admin", return_value=admin):
        response = app.test_client().post("/api/v1/admin/stock-movement-ids", headers=headers)
    assert response.status_code == expected
    assert "movement_id" not in response.get_json()


@pytest.mark.parametrize("validation,expected", [({"valid": True}, 200), ({"valid": False}, 401), (None, 502)])
def test_stock_movement_id_generation_checks_opkey_for_its_route(validation, expected):
    with patch("src.opkey_middleware.validate_op_key_with_core", return_value=validation) as validate:
        response = app.test_client().post("/api/v1/admin/stock-movement-ids", headers={"X-Op-Key": "test-key"})
    assert response.status_code == expected
    validate.assert_called_once_with("test-key", "/api/v1/admin/stock-movement-ids", "POST")
    if expected != 200:
        assert "movement_id" not in response.get_json()


def test_create_product_requires_name_and_valid_fields():
    client = app.test_client()
    with patch("src.proxy.check_admin", return_value=True):
        resp = client.post("/api/v1/admin/products", json={}, headers={"Authorization": "Bearer token"})
    assert resp.status_code == 400
    assert "name" in resp.get_data(as_text=True)


@pytest.mark.parametrize("quantity", [0, 5, None])
def test_product_update_rejects_quantity_before_core(quantity):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.controllers.admin_products_controller.admin_update_product_service") as service:
        response = app.test_client().put(
            "/api/v1/admin/products/1", json={"name": "Game", "quantity": quantity},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 400
    assert "quantity" in response.get_json()["error"]
    service.assert_not_called()


def test_product_update_accepts_other_fields():
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.controllers.admin_products_controller.admin_update_product_service", return_value={"name": "Updated"}) as service:
        response = app.test_client().put(
            "/api/v1/admin/products/1", json={"name": "Updated"},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    assert response.get_json()["name"] == "Updated"
    assert "quantity" not in service.call_args.args[1]


@pytest.mark.parametrize("payload", [
    {}, {"new_stock": True}, {"new_stock": 1.5}, {"new_stock": 1.0},
    {"new_stock": "1"}, {"new_stock": -1}, {"new_stock": 0}, {"new_stock": 2147483648},
    {"new_stock": 1, "extra": 2}, [], None,
])
def test_product_stock_rejects_invalid_body_before_core(payload):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().post(
            "/api/v1/admin/products/1/stock", json=payload,
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 400
    assert set(response.get_json()) == {"error"}
    graphql.assert_not_called()


def _movement_request(quantity=1):
    return {"movement_id": "12345678-1234-4234-8234-123456789abc", "direction": "IN", "quantity": quantity}


def _movement_response(quantity=1):
    return {"data": {"adjustProductStock": {"movementId": "12345678-1234-4234-8234-123456789abc", "status": "APPLIED",
                     "requestedQuantity": quantity, "appliedQuantity": quantity, "quantityBefore": 0, "quantityAfter": quantity, "errors": []}}}


@pytest.mark.parametrize("stock", [1, 20, 2147483647])
def test_product_stock_sends_uuid_graphql_contract(stock):
    result = _movement_response(stock)
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=result) as graphql:
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(stock),
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    assert response.get_json()["status"] == "APPLIED"
    query, variables, token = graphql.call_args.args[:3]
    assert "adjustProductStock(productId: $productId, movementId: $movementId, direction: $direction, quantity: $quantity)" in query
    assert "variantId" not in query
    assert variables == {"productId": "42", "movementId": _movement_request()["movement_id"], "direction": "IN", "quantity": stock}
    assert token == "Bearer token"


@pytest.mark.parametrize("code,status", [
    ("NOT_FOUND", 404), ("INVALID", 400), ("UNAUTHENTICATED", 401),
    ("FORBIDDEN", 403), ("SERVER_ERROR", 502), ("UNKNOWN", 502),
])
def test_product_stock_sanitizes_core_errors(code, status):
    secret = "private-upstream-detail"
    result = {"data": {"adjustProductStock": {"movementId": _movement_request()["movement_id"], "status": None, "errors": [
        {"field": ["quantity"], "code": code, "message": secret},
    ]}}}
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=result):
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(2),
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == status
    assert set(response.get_json()) == {"error", "movement_id"}
    assert secret not in response.get_data(as_text=True)


def test_product_stock_opkey_propagation_and_old_route_removed(monkeypatch):
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", "synthetic-internal-secret-0123456789-abcdef")
    result = _movement_response(2)
    with patch("src.opkey_middleware.validate_op_key_with_core", return_value={"valid": True}) as validate, \
            patch("src.proxy.requests.post") as post:
        post.return_value.json.return_value = result
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(2),
            headers={"X-Op-Key": "synthetic-key"},
        )
    assert response.status_code == 200
    validate.assert_called_once_with("synthetic-key", "/api/v1/admin/products/42/stock", "POST")
    headers = post.call_args.kwargs["headers"]
    assert headers["X-Op-Key"] == "synthetic-key"
    assert headers["X-Op-Path"] == "/api/v1/admin/products/42/stock"
    assert headers["X-Op-Method"] == "POST"
    assert headers["X-Internal-Secret"] == "synthetic-internal-secret-0123456789-abcdef"
    with patch("src.proxy._graphql_request") as graphql:
        old_response = app.test_client().post("/api/v1/admin/products/42/variants/1/adjust-stock")
    assert old_response.status_code in (404, 405)
    graphql.assert_not_called()


def test_product_stock_forwards_bearer_to_core():
    result = _movement_response(2)
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy.requests.post") as post:
        post.return_value.json.return_value = result
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(2),
            headers={"Authorization": "Bearer synthetic-token"},
        )
    assert response.status_code == 200
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
    assert "X-Internal-Secret" not in post.call_args.kwargs["headers"]


@pytest.mark.parametrize("body,content_type", [("{", "application/json"), ("{}", "text/plain"), ("", "application/json")])
def test_product_stock_rejects_missing_or_malformed_json(body, content_type):
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", data=body, content_type=content_type,
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 400
    assert set(response.get_json()) == {"error"}
    graphql.assert_not_called()


@pytest.mark.parametrize("headers,admin,expected", [
    ({}, None, 401),
    ({"X-Op-Key": "invalid-key"}, None, 401),
    ({"Authorization": "Bearer non-admin"}, False, 403),
])
def test_product_stock_denies_unauthorized_requests(headers, admin, expected):
    with patch("src.opkey_middleware.validate_op_key_with_core", return_value={"valid": False}), \
            patch("src.proxy.check_admin", return_value=admin), \
            patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(), headers=headers,
        )
    assert response.status_code == expected
    assert set(response.get_json()) == {"error", "movement_id"}
    graphql.assert_not_called()


@pytest.mark.parametrize("result", [
    {"errors": [{"message": "private detail"}]},
    {"data": {"adjustProductStock": None}},
    {"data": {"adjustProductStock": {"status": None, "errors": []}}},
    {"data": {"adjustProductStock": {"status": "APPLIED"}}},
    {"data": {"adjustProductStock": {"status": None, "errors": ["private detail"]}}},
    {"data": {"adjustProductStock": {"status": None, "errors": [{"code": []}]}}},
])
def test_product_stock_rejects_invalid_core_responses(result):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=result):
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(),
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 502
    assert response.get_json() == {"error": "Movement outcome may be uncertain. Refresh the screen and check the movement status.", "movement_id": _movement_request()["movement_id"]}


@pytest.mark.parametrize("product_id", ["0", "-1", "abc", "2147483648", "9" * 5000])
def test_product_stock_rejects_invalid_product_id(product_id):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().post(
            f"/api/v1/admin/products/{product_id}/stock", json=_movement_request(),
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 400
    graphql.assert_not_called()


def test_product_stock_accepts_maximum_product_id():
    result = _movement_response()
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=result) as graphql:
        response = app.test_client().post(
            "/api/v1/admin/products/2147483647/stock", json=_movement_request(),
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    assert graphql.call_args.args[1]["productId"] == "2147483647"


@pytest.mark.parametrize("identity,status", [
    ({"id": "1", "email": "admin@example.test", "isStaff": True, "isSuperuser": False}, 200),
    ({"id": "1", "email": "user@example.test", "isStaff": False, "isSuperuser": False}, 403),
    (None, 401),
    ({}, 502),
    ({"isStaff": True}, 502),
    ({"isStaff": "true", "isSuperuser": False}, 502),
    ({"isStaff": True, "isSuperuser": False}, 502),
])
def test_stock_admin_identity_is_classified_without_leaking_upstream(identity, status):
    stock = _movement_response()
    with patch("src.proxy._graphql_request", side_effect=[{"data": {"me": identity}}, stock]) as graphql:
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(),
            headers={"Authorization": "Bearer identity-classification-test"},
        )
    assert response.status_code == status
    assert graphql.call_count == (2 if status == 200 else 1)
    if status == 502:
        assert response.get_json() == {"error": "upstream GraphQL request failed", "movement_id": _movement_request()["movement_id"]}


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": None}, {"errors": [{"message": "private"}]}, {"errors": []}, []])
def test_stock_admin_identity_rejects_malformed_upstream(payload):
    with patch("src.proxy._graphql_request", return_value=payload):
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(),
            headers={"Authorization": "Bearer malformed-identity-test"},
        )
    assert response.status_code == 502
    assert response.get_json() == {"error": "upstream GraphQL request failed", "movement_id": _movement_request()["movement_id"]}


def test_stock_admin_revalidates_identity_after_expiry_or_revocation():
    identity = {"data": {"me": {"id": "1", "email": "admin@example.test", "isStaff": True, "isSuperuser": False}}}
    stock = _movement_response()
    with patch("src.proxy._graphql_request", side_effect=[identity, stock, {"data": {"me": None}}]) as graphql:
        client = app.test_client()
        first = client.post("/api/v1/admin/products/42/stock", json=_movement_request(),
                            headers={"Authorization": "Bearer expires-test"})
        second = client.post("/api/v1/admin/products/42/stock", json=_movement_request(),
                             headers={"Authorization": "Bearer expires-test"})
    assert first.status_code == 200
    assert second.status_code == 401
    assert graphql.call_count == 3


def test_stock_admin_identity_upstream_outage_is_sanitized():
    with patch("src.proxy.requests.post", side_effect=requests.ConnectionError("private upstream detail")):
        response = app.test_client().post(
            "/api/v1/admin/products/42/stock", json=_movement_request(),
            headers={"Authorization": "Bearer outage-test"},
        )
    assert response.status_code == 502
    assert response.get_json() == {"error": "upstream GraphQL request failed", "movement_id": _movement_request()["movement_id"]}
