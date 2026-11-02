from unittest.mock import Mock, patch

import pytest
from flask import g

from app import app


SESSION_ID = "11111111-2222-4333-8444-555555555555"
HEADERS = {"Authorization": "Bearer synthetic-admin-token"}


def test_operation_sessions_require_authentication():
    with patch("src.proxy._graphql_request") as query:
        response = app.test_client().get("/api/v1/admin/op-sessions")
    assert response.status_code == 401
    query.assert_not_called()


def test_administrator_can_list_sessions_without_key_material():
    session = {"id": SESSION_ID, "userId": "7", "ops": ["GET:/api/v1/admin/*"],
               "issuedAt": "2030-01-01T00:00:00Z", "expiresAt": None, "lastUsed": None, "revoked": False}
    payload = {"data": {"adminOpSessions": {"items": [session], "hasNext": False, "userErrors": []}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=payload) as query:
        response = app.test_client().get("/api/v1/admin/op-sessions?user_id=7", headers=HEADERS)
    assert response.status_code == 200
    assert response.get_json()["items"][0]["user_id"] == "7"
    assert "key_hash" not in response.get_data(as_text=True)
    assert query.call_args.args[1]["userId"] == "7"


@pytest.mark.parametrize("action", ["revoke", "expire"])
def test_administrator_can_close_session(action):
    payload = {"data": {"manageOpSession": {"success": True, "userErrors": []}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=payload) as query:
        response = app.test_client().post(f"/api/v1/admin/op-sessions/{SESSION_ID}/{action}", headers=HEADERS)
    assert response.status_code == 204
    assert query.call_args.args[1] == {"sessionId": SESSION_ID, "action": action.upper()}


def test_invalid_session_identifier_is_rejected_without_core_query():
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request") as query:
        response = app.test_client().post("/api/v1/admin/op-sessions/invalid/revoke", headers=HEADERS)
    assert response.status_code == 400
    query.assert_not_called()


def test_non_administrator_cannot_list_or_close_sessions():
    with patch("src.proxy.check_admin", return_value=False), patch("src.proxy._graphql_request") as query:
        client = app.test_client()
        listed = client.get("/api/v1/admin/op-sessions", headers=HEADERS)
        revoked = client.post(f"/api/v1/admin/op-sessions/{SESSION_ID}/revoke", headers=HEADERS)
    assert listed.status_code == revoked.status_code == 403
    query.assert_not_called()


def test_validated_operation_key_can_list_sessions():
    payload = {"data": {"adminOpSessions": {"items": [], "hasNext": False, "userErrors": []}}}
    with patch("app._opkey_before_request", side_effect=lambda: setattr(g, "op_session_valid", True)), \
            patch("src.proxy._graphql_request", return_value=payload) as query:
        response = app.test_client().get("/api/v1/admin/op-sessions", headers={"X-Op-Key": "synthetic-op-key"})
    assert response.status_code == 200
    assert query.call_count == 1


def test_validated_opkey_reaches_audit_and_coupon_graphql_requests(monkeypatch):
    secret = "synthetic-internal-secret-0123456789-abcdef"
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", secret)
    responses = [
        {"data": {"adminAuditLogs": {"records": [], "nextCursor": None}}},
        {"data": {"adminCoupons": []}},
        {"data": {"createAdminCoupon": {"coupon": {
            "id": 4,
            "code": "SAVE10",
            "discountPercent": 10,
            "remaining": 3,
            "active": True,
            "startsAt": None,
            "endsAt": None,
            "createdAt": "2026-11-02T00:00:00+00:00",
        }, "userErrors": []}}},
    ]

    def graphql_response(payload):
        response = Mock(status_code=200)
        response.json.return_value = payload
        return response

    with patch("app._opkey_before_request", side_effect=lambda: setattr(g, "op_session_valid", True)), \
            patch("src.proxy.requests.post", side_effect=[graphql_response(body) for body in responses]) as post:
        client = app.test_client()
        headers = {"X-Op-Key": "synthetic-op-key"}
        listed_audit = client.get("/api/v1/admin/audit", headers=headers)
        listed_coupons = client.get("/api/v1/admin/coupons", headers=headers)
        created_coupon = client.post(
            "/api/v1/admin/coupons",
            json={"code": "SAVE10", "discount_percent": 10, "remaining": 3, "active": True},
            headers=headers,
        )

    assert [listed_audit.status_code, listed_coupons.status_code, created_coupon.status_code] == [200, 200, 201]
    assert created_coupon.get_json()["id"] == 4
    expected_routes = [
        ("GET", "/api/v1/admin/audit"),
        ("GET", "/api/v1/admin/coupons"),
        ("POST", "/api/v1/admin/coupons"),
    ]
    for call, (method, path) in zip(post.call_args_list, expected_routes):
        forwarded = call.kwargs["headers"]
        assert forwarded == {
            "X-Op-Key": "synthetic-op-key",
            "X-Internal-Secret": secret,
            "X-Op-Method": method,
            "X-Op-Path": path,
        }


@pytest.mark.parametrize("path", ["?page=0", "?page_size=101", "?user_id=invalid"])
def test_invalid_session_filters_do_not_query_core(path):
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request") as query:
        response = app.test_client().get(f"/api/v1/admin/op-sessions{path}", headers=HEADERS)
    assert response.status_code == 400
    query.assert_not_called()


def test_graphql_errors_are_sanitized_even_when_data_is_present():
    payload = {"data": {"adminOpSessions": {"items": [], "hasNext": False, "userErrors": []}},
               "errors": [{"message": "synthetic-private-detail"}]}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=payload):
        response = app.test_client().get("/api/v1/admin/op-sessions", headers=HEADERS)
    assert response.status_code == 502
    assert b"synthetic-private-detail" not in response.data


@pytest.mark.parametrize("code,status", [("NOT_FOUND", 404), ("FORBIDDEN", 403), ("INVALID", 400), ("OTHER", 502)])
def test_manage_session_maps_domain_errors_without_details(code, status):
    payload = {"data": {"manageOpSession": {"success": False, "userErrors": [{"code": code, "message": "private"}]}}}
    with patch("src.proxy.check_admin", return_value=True), patch("src.proxy._graphql_request", return_value=payload):
        response = app.test_client().post(f"/api/v1/admin/op-sessions/{SESSION_ID}/revoke", headers=HEADERS)
    assert response.status_code == status
    assert b"private" not in response.data