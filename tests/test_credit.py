from unittest.mock import MagicMock, patch

import pytest
import requests
from flask import request
from werkzeug.exceptions import HTTPException

from app import app


TOKEN = "Bearer synthetic-token"
KEY = "11111111-2222-4333-8444-555555555555"
CODE = "a" * 64
HEADERS = {"Authorization": TOKEN, "Idempotency-Key": KEY}
BALANCE = {"balance": "25.00", "currency": "ARS"}
ORDER = {
    "id": KEY, "status": "paid", "total": 20.0, "currency": "ARS",
    "shippingMode": "standard", "recipient": "Buyer", "street": "Main St",
    "city": "City", "postalCode": "1000", "phone": None,
    "paymentStatus": "approved", "paymentStatusDetail": "credit",
    "createdAt": "2026-10-27T12:00:00Z", "paidAt": "2026-10-27T12:00:00Z",
    "lines": [{"bggId": 1, "name": "Game", "unitPrice": 20.0, "quantity": 1, "subtotal": 20.0}],
    "invoice": {"number": 123, "issuedAt": "2026-10-27T12:00:00Z", "total": 20.0},
}


def test_incoming_log_never_records_untrusted_secrets():
    secret = "synthetic-secret-123"
    with patch.dict(app.error_handler_spec[None][None], {HTTPException: lambda error: error}), patch("app._append_incoming_log") as log, patch("app._opkey_before_request", return_value=None):
        app.test_client().get(
            f"/api/v1/unknown/{secret}?token={secret}",
            headers={"Authorization": f"Bearer {secret}", "X-Request-ID": secret, "X-Custom-Secret": secret},
        )
    log.assert_called_once()
    entry = log.call_args.args[0]
    assert secret not in str(entry)
    assert "headers" not in entry and "full_url" not in entry
    assert "path" in entry and "correlation_id" in entry


def test_debug_headers_never_logs_secrets(capsys, caplog):
    secret = "synthetic-debug-secret-123"
    with patch("app._append_incoming_log") as incoming_log, patch("app._opkey_before_request", return_value=None), patch("builtins.open", create=True) as file_open:
        result = app.test_client().post(
            "/api/v1/_debug/headers",
            json={"headers": {"Authorization": secret}, "code": secret},
            headers={"Authorization": f"Bearer {secret}", "X-Custom-Secret": secret},
        )
    assert result.status_code == 204
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + caplog.text
    assert secret not in str(incoming_log.call_args_list)
    assert secret not in str(file_open.mock_calls)


def test_global_error_handlers_sanitize_exceptions_and_do_not_write_logs(capsys, caplog):
    from app import _handle_unexpected_exception, _handle_upstream_error
    from src.proxy import UpstreamError
    from werkzeug.exceptions import NotFound

    secret = "synthetic-private-error-detail"
    with app.test_request_context(f"/api/v1/{secret}"), patch("builtins.open") as file_open:
        upstream_response, upstream_status = _handle_upstream_error(UpstreamError(secret, "UPSTREAM"))
        try:
            raise RuntimeError(secret)
        except RuntimeError as error:
            unexpected_response, unexpected_status = _handle_unexpected_exception(error)
        not_found = NotFound()
        assert _handle_unexpected_exception(not_found) is not_found
    assert upstream_status == 502 and unexpected_status == 500
    assert secret not in upstream_response.get_data(as_text=True) + unexpected_response.get_data(as_text=True)
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    file_open.assert_not_called()


def test_global_error_handler_sanitizes_flask_response(capsys, caplog):
    secret = "synthetic-private-error-detail"
    with patch("app.get_credit", side_effect=RuntimeError(secret)), \
            patch("app._opkey_before_request", return_value=None), \
            patch("app._append_incoming_log"), patch("builtins.open") as file_open:
        response = app.test_client().get("/api/v1/credit", headers={"Authorization": f"Bearer {secret}"})
        missing = app.test_client().get("/missing-route")
    assert response.status_code == 500
    assert missing.status_code == 404
    captured = capsys.readouterr()
    assert secret not in response.get_data(as_text=True) + captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    file_open.assert_not_called()


def upstream(payload):
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    return response


def test_get_balance_forwards_authentication():
    payload = {"data": {"myCredit": {"credit": {"balance": "25.00", "currency": "ARS"}, "userErrors": []}}}
    with patch.dict(app.error_handler_spec[None][None], {HTTPException: lambda error: error}), patch("requests.post", return_value=upstream(payload)) as post:
        result = app.test_client().get("/api/v1/credit", headers={"Authorization": TOKEN})
    assert result.status_code == 200
    assert result.get_json() == {"balance": "25.00", "currency": "ARS"}
    assert result.headers["Cache-Control"] == "no-store"
    assert post.call_args.kwargs["headers"]["Authorization"] == TOKEN


@pytest.mark.parametrize("authorization", ["bearer synthetic-token", "BEARER   synthetic-token", "Bearer\tsynthetic-token"])
def test_bearer_is_normalized_before_forwarding(authorization):
    payload = {"data": {"myCredit": {"credit": BALANCE, "userErrors": []}}}
    with patch("requests.post", return_value=upstream(payload)) as post:
        result = app.test_client().get("/api/v1/credit", headers={"Authorization": authorization})
    assert result.status_code == 200
    assert post.call_args.kwargs["headers"]["Authorization"] == TOKEN


@pytest.mark.parametrize("field,limit", [("recipient", 250), ("street", 500), ("city", 150), ("postal_code", 32), ("phone", 50)])
def test_checkout_address_limits_follow_contract_and_core(field, limit):
    payload = {"data": {"checkoutWithCredit": {"order": ORDER, "credit": BALANCE, "userErrors": []}}}
    with patch("requests.post", return_value=upstream(payload)) as post:
        result = app.test_client().post("/api/v1/checkout/credit", json={"shipping_mode": "pickup", "address": {field: "x" * limit}}, headers=HEADERS)
    assert result.status_code == 200
    core_field = "postalCode" if field == "postal_code" else field
    assert post.call_args.kwargs["json"]["variables"]["input"]["address"][core_field] == "x" * limit
    with patch("requests.post") as post:
        result = app.test_client().post("/api/v1/checkout/credit", json={"shipping_mode": "pickup", "address": {field: "x" * (limit + 1)}}, headers=HEADERS)
    assert result.status_code == 400
    assert result.json["errors"][0]["code"] == "INVALID"
    post.assert_not_called()


def test_checkout_rejects_address_over_limit_before_trimming():
    with patch("requests.post") as post:
        result = app.test_client().post(
            "/api/v1/checkout/credit",
            json={"shipping_mode": "pickup", "address": {"recipient": " " + "x" * 250}},
            headers=HEADERS,
        )
    assert result.status_code == 400
    assert result.json["errors"][0]["code"] == "INVALID"
    post.assert_not_called()


@pytest.mark.parametrize("path", ["/api/v1/gift-cards/redeem", "/api/v1/checkout/credit"])
@pytest.mark.parametrize("streamed", [False, True])
def test_credit_body_limit_is_sanitized(path, streamed, capsys, caplog):
    body = '{"code":"' + CODE * 1100 + '"}'
    environ = {"wsgi.input_terminated": True, "CONTENT_LENGTH": ""} if streamed else {}
    with patch("requests.post") as post, patch("app._append_incoming_log") as log:
        result = app.test_client().post(path, data=body, content_type="application/json", headers=HEADERS, environ_overrides=environ)
    assert result.status_code == 400
    assert result.json == {"errors": [{"code": "INVALID", "message": "Invalid request."}]}
    assert result.headers["Cache-Control"] == "no-store"
    post.assert_not_called()
    log.assert_not_called()
    captured = capsys.readouterr()
    assert CODE not in result.get_data(as_text=True) + captured.out + captured.err + caplog.text


def test_streamed_valid_json_with_oversized_padding_is_rejected():
    body = '{"code":"' + CODE + '"}' + " " * 70000
    with patch("requests.post") as post:
        result = app.test_client().post(
            "/api/v1/gift-cards/redeem", data=body, content_type="application/json", headers=HEADERS,
            environ_overrides={"wsgi.input_terminated": True, "CONTENT_LENGTH": ""},
        )
    assert result.status_code == 400
    post.assert_not_called()


def test_credit_body_at_limit_and_escaped_unicode_are_accepted():
    payload = {"data": {"redeemGiftCard": {"credit": BALANCE, "userErrors": []}}}
    body = '{"code":"' + CODE + '"}'
    body += " " * (64 * 1024 - len(body))
    with patch("requests.post", return_value=upstream(payload)) as post:
        result = app.test_client().post("/api/v1/gift-cards/redeem", data=body, content_type="application/json", headers=HEADERS)
    assert result.status_code == 200
    assert post.call_args.kwargs["json"]["variables"]["input"]["code"] == CODE

    payload = {"data": {"checkoutWithCredit": {"order": ORDER, "credit": BALANCE, "userErrors": []}}}
    address = {"recipient": "\U0001f3b2" * 250, "street": "\U0001f3b2" * 500, "city": "\U0001f3b2" * 150, "postal_code": "\U0001f3b2" * 32, "phone": "\U0001f3b2" * 50}
    with patch("requests.post", return_value=upstream(payload)) as post:
        result = app.test_client().post("/api/v1/checkout/credit", json={"shipping_mode": "pickup", "address": address}, headers=HEADERS)
    assert result.status_code == 200
    assert post.call_args.kwargs["json"]["variables"]["input"]["address"]["street"] == address["street"]


def test_credit_body_limit_does_not_affect_other_routes():
    with patch("requests.post"):
        app.test_client().post("/api/v1/gift-cards/redeem", data="x" * 70000, content_type="application/json", headers=HEADERS)
    with patch("app._opkey_before_request", return_value=None), patch("app.health_controller", side_effect=lambda: str(len(request.get_data()))):
        result = app.test_client().get("/health", data="x" * 70000)
    assert result.get_data(as_text=True) == "70000"


def test_pending_payment_is_conflict_and_sanitized():
    payload = {"data": {"checkoutWithCredit": {"order": None, "credit": None, "userErrors": [{"code": "PENDING_PAYMENT", "message": TOKEN}]}}}
    with patch.dict(app.error_handler_spec[None][None], {HTTPException: lambda error: error}), patch("requests.post", return_value=upstream(payload)):
        result = app.test_client().post("/api/v1/checkout/credit", json={"shipping_mode": "pickup"}, headers={"Authorization": TOKEN, "Idempotency-Key": KEY})
    assert result.status_code == 409
    assert result.get_json()["errors"][0]["code"] == "PENDING_PAYMENT"
    assert TOKEN not in result.get_data(as_text=True)


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/v1/credit", None),
    ("post", "/api/v1/gift-cards/redeem", {"code": CODE}),
    ("post", "/api/v1/checkout/credit", {"shipping_mode": "pickup"}),
])
@pytest.mark.parametrize("authorization", [None, "", "Basic secret", "Bearer "])
def test_requires_bearer_without_upstream_call(method, path, body, authorization):
    headers = {"Idempotency-Key": KEY}
    if authorization is not None:
        headers["Authorization"] = authorization
    with patch("requests.post") as post:
        result = app.test_client().open(path, method=method, json=body, headers=headers)
    assert result.status_code == 401
    assert result.headers["Cache-Control"] == "no-store"
    post.assert_not_called()


@pytest.mark.parametrize("path,body", [
    ("/api/v1/gift-cards/redeem", {"code": CODE}),
    ("/api/v1/checkout/credit", {"shipping_mode": "pickup"}),
])
@pytest.mark.parametrize("key", [None, "", "invalid", "11111111-2222"])
def test_invalid_idempotency_key_does_not_call_core(path, body, key):
    headers = {"Authorization": TOKEN}
    if key is not None:
        headers["Idempotency-Key"] = key
    with patch("requests.post") as post:
        result = app.test_client().post(path, json=body, headers=headers)
    assert result.status_code == 400
    assert result.headers["Cache-Control"] == "no-store"
    post.assert_not_called()


@pytest.mark.parametrize("body", [None, {}, {"code": 3}, {"code": CODE, "user_id": 1}, [CODE]])
def test_redeem_rejects_invalid_body(body):
    with patch("requests.post") as post:
        result = app.test_client().post("/api/v1/gift-cards/redeem", json=body, headers=HEADERS)
    assert result.status_code == 400
    post.assert_not_called()


@pytest.mark.parametrize("body", [None, {}, {"shipping_mode": "express"}, {"shipping_mode": "pickup", "user_id": 1}, {"shipping_mode": "standard", "address": {"postal_code": 123}}, {"shipping_mode": "pickup", "address": None}, {"shipping_mode": "pickup", "address": {"phone": None}}, {"shipping_mode": "pickup", "address": {"phone": " " * 256}}])
def test_checkout_rejects_invalid_body(body):
    with patch("requests.post") as post:
        result = app.test_client().post("/api/v1/checkout/credit", json=body, headers=HEADERS)
    assert result.status_code == 400
    post.assert_not_called()


def test_redeem_retries_forward_same_input_without_logging(capsys, caplog):
    payload = {"data": {"redeemGiftCard": {"credit": BALANCE, "userErrors": []}}}
    with patch("requests.post", return_value=upstream(payload)) as post, patch("app._append_incoming_log") as log:
        client = app.test_client()
        first = client.post("/api/v1/gift-cards/redeem", json={"code": CODE}, headers=HEADERS)
        second = client.post("/api/v1/gift-cards/redeem", json={"code": CODE}, headers=HEADERS)
    assert first.status_code == second.status_code == 200
    assert first.get_json() == second.get_json() == BALANCE
    assert first.headers["Cache-Control"] == "no-store"
    assert post.call_count == 2
    for call in post.call_args_list:
        assert call.kwargs["json"]["variables"] == {"input": {"code": CODE, "idempotencyKey": KEY}}
        assert call.kwargs["headers"]["Authorization"] == TOKEN
        assert call.kwargs["allow_redirects"] is False
    log.assert_not_called()
    captured = capsys.readouterr()
    assert all(secret not in captured.out + captured.err + caplog.text for secret in (TOKEN, CODE, KEY))


def test_checkout_forwards_address_and_returns_paid_order_snapshot():
    payload = {"data": {"checkoutWithCredit": {"order": ORDER, "credit": BALANCE, "userErrors": []}}}
    body = {"shipping_mode": "standard", "address": {"recipient": " Buyer ", "postal_code": "1000"}}
    with patch("requests.post", return_value=upstream(payload)) as post:
        result = app.test_client().post("/api/v1/checkout/credit", json=body, headers=HEADERS)
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json["credit"] == BALANCE
    assert result.json["order"]["status"] == "paid"
    assert result.json["order"]["lines"][0]["bgg_id"] == 1
    assert result.json["order"]["invoice"] == {"number": 123, "issued_at": "2026-10-27T12:00:00Z", "total": 20.0}
    assert post.call_args.kwargs["json"]["variables"] == {"input": {"shippingMode": "STANDARD", "address": {"recipient": " Buyer ", "postalCode": "1000"}, "idempotencyKey": KEY}}


def test_checkout_preserves_different_payloads_for_core_idempotency():
    payload = {"data": {"checkoutWithCredit": {"order": ORDER, "credit": BALANCE, "userErrors": []}}}
    with patch("requests.post", return_value=upstream(payload)) as post:
        client = app.test_client()
        for address in ({"recipient": "Buyer"}, {"recipient": " Buyer "}):
            client.post("/api/v1/checkout/credit", json={"shipping_mode": "pickup", "address": address}, headers=HEADERS)
    inputs = [call.kwargs["json"]["variables"]["input"] for call in post.call_args_list]
    assert inputs[0]["idempotencyKey"] == inputs[1]["idempotencyKey"] == KEY
    assert inputs[0]["address"] != inputs[1]["address"]


@pytest.mark.parametrize("field,path,body,code,status", [
    ("myCredit", "/api/v1/credit", None, "UNAUTHENTICATED", 401),
    ("redeemGiftCard", "/api/v1/gift-cards/redeem", {"code": CODE}, "INVALID_GIFT_CARD", 422),
    ("redeemGiftCard", "/api/v1/gift-cards/redeem", {"code": CODE}, "IDEMPOTENCY_CONFLICT", 409),
    ("checkoutWithCredit", "/api/v1/checkout/credit", {"shipping_mode": "pickup"}, "IDEMPOTENCY_CONFLICT", 409),
    ("checkoutWithCredit", "/api/v1/checkout/credit", {"shipping_mode": "pickup"}, "INSUFFICIENT_CREDIT", 409),
    ("checkoutWithCredit", "/api/v1/checkout/credit", {"shipping_mode": "pickup"}, "INSUFFICIENT_STOCK", 409),
    ("checkoutWithCredit", "/api/v1/checkout/credit", {"shipping_mode": "pickup"}, "EMPTY_CART", 422),
    ("checkoutWithCredit", "/api/v1/checkout/credit", {"shipping_mode": "pickup"}, "ADDRESS_REQUIRED", 400),
])
def test_core_errors_are_sanitized(field, path, body, code, status):
    payload = {"data": {field: {"userErrors": [{"code": code, "message": TOKEN + CODE, "field": [TOKEN]}]}}}
    with patch("requests.post", return_value=upstream(payload)):
        result = app.test_client().open(path, method="GET" if body is None else "POST", json=body, headers=HEADERS)
    assert result.status_code == status
    expected_code = "ADDRESS_REQUIRED_RECORDED" if field == "checkoutWithCredit" and code == "ADDRESS_REQUIRED" else code
    assert result.json["errors"][0]["code"] == expected_code
    assert TOKEN not in result.get_data(as_text=True)
    assert CODE not in result.get_data(as_text=True)
    assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("payload", [
    {"errors": [{"message": TOKEN + CODE}]},
    {"data": {"redeemGiftCard": {"userErrors": [{"code": TOKEN + CODE}]}}},
    {"data": {"redeemGiftCard": {"userErrors": [], "credit": {"balance": "1.0", "currency": "ARS"}}}},
    {"data": {"redeemGiftCard": {"userErrors": [], "credit": {"balance": "1.00", "currency": "USD"}}}},
    {"data": {}},
])
def test_malformed_upstream_response_is_sanitized(payload):
    with patch("requests.post", return_value=upstream(payload)):
        result = app.test_client().post("/api/v1/gift-cards/redeem", json={"code": CODE}, headers=HEADERS)
    assert result.status_code == 502
    assert result.json == {"error": "Credit service unavailable"}
    assert result.headers["Cache-Control"] == "no-store"


def test_timeout_is_sanitized_without_logging(capsys, caplog):
    with patch("requests.post", side_effect=requests.Timeout(TOKEN + CODE)), patch("app._append_incoming_log") as log:
        result = app.test_client().post("/api/v1/gift-cards/redeem", json={"code": CODE}, headers=HEADERS)
    assert result.status_code == 502
    assert result.json == {"error": "Credit service unavailable"}
    log.assert_not_called()
    captured = capsys.readouterr()
    assert all(secret not in captured.out + captured.err + caplog.text for secret in (TOKEN, CODE, KEY))


@pytest.mark.parametrize("path,method,body", [
    ("/api/v1/credit", "GET", None),
    ("/api/v1/gift-cards/redeem", "POST", {"code": CODE}),
    ("/api/v1/checkout/credit", "POST", {"shipping_mode": "pickup"}),
])
def test_credit_does_not_invoke_opkey_middleware(path, method, body):
    with patch("src.opkey_middleware.validate_op_key_with_core") as validate, patch("requests.post", side_effect=requests.Timeout()):
        result = app.test_client().open(path, method=method, json=body, headers={**HEADERS, "X-Op-Key": CODE})
    assert result.status_code == 502
    validate.assert_not_called()


def test_opkey_middleware_remains_active_for_existing_routes():
    with patch("app._opkey_before_request") as middleware:
        app.test_client().get("/health")
    middleware.assert_called_once_with()


@pytest.mark.parametrize("status", [200, 403])
def test_opkey_validation_does_not_log_credentials_or_provider_response(status, capsys, caplog):
    from src.opkey_middleware import validate_op_key_with_core

    key = "synthetic-private-opkey"
    path = "/private/synthetic-path-secret"
    private_response = "synthetic-private-upstream-response"
    response = MagicMock(status_code=status, text=private_response)
    response.json.return_value = {"valid": True}
    with patch("src.opkey_middleware.requests.post", return_value=response) as post, \
            patch("builtins.open", create=True) as file_open:
        result = validate_op_key_with_core(key, path, "POST")
    assert result == ({"valid": True} if status == 200 else None)
    assert post.call_args.kwargs["json"] == {"op_key": key, "path": path, "method": "POST"}
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    assert all(value not in logs for value in (key, key[:6], key[-4:], path, private_response))
    file_open.assert_not_called()


def test_opkey_validation_timeout_fails_closed_without_logging(capsys, caplog):
    from src.opkey_middleware import validate_op_key_with_core

    secret = "synthetic-private-timeout"
    with patch("src.opkey_middleware.requests.post", side_effect=requests.Timeout(secret)), \
            patch("builtins.open", create=True) as file_open:
        result = validate_op_key_with_core("synthetic-key", "/private/path", "POST")
    assert result is None
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + caplog.text
    file_open.assert_not_called()


def test_upstream_redirect_is_not_followed():
    redirected = upstream({})
    redirected.status_code = 302
    with patch("requests.post", return_value=redirected) as post:
        result = app.test_client().post("/api/v1/gift-cards/redeem", json={"code": CODE}, headers=HEADERS)
    assert result.status_code == 502
    assert post.call_args.kwargs["allow_redirects"] is False


def test_retry_after_unknown_result_reuses_idempotency_key():
    payload = {"data": {"redeemGiftCard": {"credit": BALANCE, "userErrors": []}}}
    with patch("requests.post", side_effect=[requests.Timeout(), upstream(payload)]) as post:
        client = app.test_client()
        first = client.post("/api/v1/gift-cards/redeem", json={"code": CODE}, headers=HEADERS)
        retry = client.post("/api/v1/gift-cards/redeem", json={"code": CODE}, headers=HEADERS)
    assert first.status_code == 502
    assert retry.status_code == 200
    assert post.call_args_list[0].kwargs["json"]["variables"] == post.call_args_list[1].kwargs["json"]["variables"]


@pytest.mark.parametrize("order", [{**ORDER, "status": "pending_payment"}, {**ORDER, "invoice": None}])
def test_invalid_checkout_snapshot_is_upstream_failure(order):
    payload = {"data": {"checkoutWithCredit": {"order": order, "credit": BALANCE, "userErrors": []}}}
    with patch("requests.post", return_value=upstream(payload)):
        result = app.test_client().post("/api/v1/checkout/credit", json={"shipping_mode": "pickup"}, headers=HEADERS)
    assert result.status_code == 502