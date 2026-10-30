from unittest.mock import MagicMock, patch
import traceback

import pytest
import requests

from app import app
from src.proxy import UpstreamError, _graphql_request, checkout, get_invoice, get_order, get_orders, list_products, retry_payment


ORDER_ID = "11111111-2222-4333-8444-555555555555"
ORDER = {
    "id": ORDER_ID,
    "status": "pending_payment",
    "total": 25.0,
    "currency": "ARS",
    "shipping_mode": "standard",
    "recipient": "Buyer",
    "street": "1 Main St",
    "city": "Buenos Aires",
    "postal_code": "1000",
    "phone": None,
    "payment_status": "rejected",
    "payment_status_detail": "cc_rejected_insufficient_amount",
    "created_at": "2026-10-20T10:00:00+00:00",
    "paid_at": None,
    "lines": [{
        "bgg_id": 7,
        "name": "Game",
        "unit_price": 12.5,
        "quantity": 2,
        "subtotal": 25.0,
    }],
    "invoice": None,
}


@pytest.mark.parametrize("failure", [False, True])
def test_graphql_proxy_never_logs_headers_variables_or_upstream_details(failure, capsys, caplog):
    token = "Bearer synthetic-buyer-secret"
    op_key = "synthetic-op-key"
    private_value = "synthetic-private-value"
    response = MagicMock()
    response.json.return_value = {"data": {"result": private_value}, "errors": [{"message": private_value}]}
    caplog.set_level("INFO")
    with app.test_request_context("/api/v1/checkout", headers={"X-Op-Key": op_key}), \
            patch("builtins.open", create=True) as file_open, \
            patch("requests.post", side_effect=requests.Timeout(private_value) if failure else None, return_value=response) as post:
        if failure:
            with pytest.raises(UpstreamError) as raised:
                _graphql_request("query Example { result }", {"address": private_value}, token)
            assert private_value not in str(raised.value)
            assert private_value not in "".join(traceback.format_exception(raised.value))
        else:
            _graphql_request("query Example { result }", {"address": private_value}, token)
        assert post.call_args.kwargs["headers"]["Authorization"] == token
        assert post.call_args.kwargs["headers"]["X-Op-Key"] == op_key
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    for secret in (token, op_key, private_value):
        assert secret not in logs


@pytest.mark.parametrize("failure", ["none", "timeout", "graphql"])
def test_product_proxy_does_not_log_credentials_or_request_details(failure, capsys, caplog):
    token = "Bearer synthetic-private-token"
    search = "synthetic-private-search"
    response = MagicMock()
    response.json.return_value = (
        {"errors": [{"message": search}]} if failure == "graphql" else
        {"data": {"products": {"items": [], "page": 1, "pageSize": 50, "total": 0, "totalPages": 0}}}
    )
    caplog.set_level("INFO")
    with patch("builtins.open", create=True) as file_open, \
            patch("requests.post", side_effect=requests.Timeout(search) if failure == "timeout" else None, return_value=response) as post:
        if failure == "none":
            assert list_products(search=search, token=token)["items"] == []
        else:
            with pytest.raises(UpstreamError) as raised:
                list_products(search=search, token=token)
            assert search not in "".join(traceback.format_exception(raised.value))
        assert post.call_args.kwargs["headers"]["Authorization"] == token
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    assert token not in logs and search not in logs


def test_invoice_timeout_does_not_expose_upstream_details(capsys, caplog):
    secret = "synthetic-private-invoice-error"
    with patch("src.proxy._graphql_request", return_value={"data": {"myOrders": []}}), \
            patch("requests.get", side_effect=requests.Timeout(secret)), patch("builtins.open", create=True) as file_open:
        with pytest.raises(UpstreamError) as raised:
            get_invoice(ORDER_ID, "Bearer synthetic-token")
    assert secret not in "".join(traceback.format_exception(raised.value))
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + caplog.text + str(file_open.mock_calls)


def test_all_order_routes_require_authorization():
    client = app.test_client()
    responses = [
        client.post("/api/v1/checkout", json={"shipping_mode": "pickup"}),
        client.post(
            f"/api/v1/orders/{ORDER_ID}/retry-payment", headers={"Authorization": ""}
        ),
        client.post(
            "/api/v1/checkout/confirm",
            json={"order_id": ORDER_ID, "payment_id": "123"},
        ),
        client.get("/api/v1/orders"),
        client.get(f"/api/v1/orders/{ORDER_ID}"),
        client.get(f"/api/v1/orders/{ORDER_ID}/invoice"),
    ]
    assert [response.status_code for response in responses] == [401] * len(responses)
    assert all(response.get_json()["errors"][0]["code"] == "UNAUTHENTICATED" for response in responses)


def test_invalid_core_bearer_is_401_and_core_outage_is_502():
    client = app.test_client()
    with patch("app.get_orders", side_effect=UpstreamError("Authentication is required.", "UNAUTHENTICATED")):
        unauthorized = client.get("/api/v1/orders", headers={"Authorization": "Bearer invalid"})
    assert unauthorized.status_code == 401
    assert unauthorized.get_json()["errors"][0]["code"] == "UNAUTHENTICATED"

    with patch("app.get_orders", side_effect=UpstreamError("Connection refused")):
        unavailable = client.get("/api/v1/orders", headers={"Authorization": "Bearer buyer-token"})
    assert unavailable.status_code == 502
    assert unavailable.get_json() == {"error": "upstream GraphQL request failed"}


def test_checkout_validates_shipping_address_and_rejects_user_ids():
    client = app.test_client()
    headers = {"Authorization": "Bearer buyer-token"}
    assert client.post("/api/v1/checkout", json={"shipping_mode": "express"}, headers=headers).status_code == 400
    assert client.post("/api/v1/checkout", json={"shipping_mode": "standard", "user_id": 8}, headers=headers).status_code == 400
    assert client.post("/api/v1/checkout", json={"shipping_mode": "pickup", "address": "home"}, headers=headers).status_code == 400
    assert client.post(
        "/api/v1/checkout",
        json={"shipping_mode": "standard", "address": {"recipient": 5}},
        headers=headers,
    ).status_code == 400


@pytest.mark.parametrize("field,limit", [("recipient", 250), ("street", 500), ("city", 150), ("postal_code", 32), ("phone", 50)])
def test_checkout_address_field_boundaries(field, limit):
    client = app.test_client()
    headers = {"Authorization": "Bearer buyer-token"}
    with patch("app.checkout", return_value={"order": ORDER, "init_point": "https://pay.example/1"}) as service:
        valid = client.post("/api/v1/checkout", json={"shipping_mode": "pickup", "address": {field: "x" * limit}}, headers=headers)
    assert valid.status_code == 200
    service.assert_called_once()
    with patch("app.checkout", return_value={"order": ORDER, "init_point": "https://pay.example/1"}) as service:
        invalid = client.post("/api/v1/checkout", json={"shipping_mode": "pickup", "address": {field: "x" * (limit + 1)}}, headers=headers)
    assert invalid.status_code == 400
    service.assert_not_called()


@pytest.mark.parametrize("address", [None, {"phone": None}])
def test_checkout_rejects_explicit_null_address_values(address):
    with patch("app.checkout", return_value={"order": ORDER, "init_point": "https://pay.example/1"}) as service:
        result = app.test_client().post("/api/v1/checkout", json={"shipping_mode": "pickup", "address": address}, headers={"Authorization": "Bearer buyer-token"})
    assert result.status_code == 400
    service.assert_not_called()


def test_checkout_rejects_address_over_limit_before_trimming():
    with patch("app.checkout", return_value={"order": ORDER, "init_point": "https://pay.example/1"}) as service:
        result = app.test_client().post("/api/v1/checkout", json={"shipping_mode": "pickup", "address": {"recipient": " " + "x" * 250}}, headers={"Authorization": "Bearer buyer-token"})
    assert result.status_code == 400
    service.assert_not_called()


def test_checkout_forwards_validated_input_and_returns_order_and_init_point():
    address = {
        "recipient": "Buyer", "street": "1 Main St", "city": "Buenos Aires",
        "postal_code": "1000", "phone": "555-0100",
    }
    with patch("app.checkout", return_value={"order": ORDER, "init_point": "https://pay.example/1"}) as service:
        response = app.test_client().post(
            "/api/v1/checkout", json={"shipping_mode": "standard", "address": address},
            headers={"Authorization": "Bearer buyer-token"},
        )
    assert response.status_code == 200
    assert response.get_json() == {"order": ORDER, "init_point": "https://pay.example/1"}
    service.assert_called_once_with("standard", address, "Bearer buyer-token")


def test_retry_payment_validates_uuid_and_forwards_bearer_token():
    client = app.test_client()
    assert client.post("/api/v1/orders/not-a-uuid/retry-payment", headers={"Authorization": "Bearer x"}).status_code == 400
    with patch("app.retry_payment", return_value={"order": ORDER, "init_point": "https://pay.example/2"}) as service:
        response = client.post(
            f"/api/v1/orders/{ORDER_ID}/retry-payment", headers={"Authorization": "Bearer buyer-token"}
        )
    assert response.status_code == 200
    assert response.get_json()["init_point"] == "https://pay.example/2"
    service.assert_called_once_with(ORDER_ID, "Bearer buyer-token")


def test_retry_payment_pending_reconciliation_returns_conflict():
    error = UpstreamError("A payment attempt requires reconciliation.", "PENDING_PAYMENT", user_error=True)
    with patch("app.retry_payment", side_effect=error):
        response = app.test_client().post(
            f"/api/v1/orders/{ORDER_ID}/retry-payment", headers={"Authorization": "Bearer buyer-token"}
        )
    assert response.status_code == 409
    assert response.get_json()["errors"][0]["code"] == "PENDING_PAYMENT"


def test_retry_payment_review_returns_conflict():
    error = UpstreamError("Payment requires manual review.", "PAYMENT_REQUIRES_REVIEW", user_error=True)
    with patch("app.retry_payment", side_effect=error):
        response = app.test_client().post(
            f"/api/v1/orders/{ORDER_ID}/retry-payment", headers={"Authorization": "Bearer buyer-token"}
        )
    assert response.status_code == 409
    assert response.get_json()["errors"][0]["code"] == "PAYMENT_REQUIRES_REVIEW"


@pytest.mark.parametrize("payment_id", [None, "", " ", "a" * 129, "id/../../x", True, 1.2])
def test_confirm_rejects_invalid_payment_ids(payment_id):
    response = app.test_client().post(
        "/api/v1/checkout/confirm",
        json={"order_id": ORDER_ID, "payment_id": payment_id},
        headers={"Authorization": "Bearer buyer-token"},
    )
    assert response.status_code == 400


def test_confirm_validates_order_uuid_and_accepts_numeric_payment_id():
    client = app.test_client()
    assert client.post(
        "/api/v1/checkout/confirm", json={"order_id": "bad", "payment_id": "123"},
        headers={"Authorization": "Bearer buyer-token"},
    ).status_code == 400
    with patch("app.confirm_payment", return_value={"order": ORDER}) as service:
        response = client.post(
            "/api/v1/checkout/confirm", json={"order_id": ORDER_ID, "payment_id": 123456},
            headers={"Authorization": "Bearer buyer-token"},
        )
    assert response.status_code == 200
    assert response.get_json() == {"order": ORDER}
    service.assert_called_once_with(ORDER_ID, "123456", "Bearer buyer-token")


def test_confirm_late_payment_returns_manual_review_conflict():
    error = UpstreamError("Payment requires manual review.", "PAYMENT_REQUIRES_REVIEW", user_error=True)
    with patch("app.confirm_payment", side_effect=error):
        response = app.test_client().post(
            "/api/v1/checkout/confirm", json={"order_id": ORDER_ID, "payment_id": "123456"},
            headers={"Authorization": "Bearer buyer-token"},
        )
    assert response.status_code == 409
    assert response.get_json()["errors"][0]["code"] == "PAYMENT_REQUIRES_REVIEW"


def test_list_and_detail_orders_forward_auth_and_validate_path_uuid():
    client = app.test_client()
    with patch("app.get_orders", return_value=[ORDER]) as list_service:
        listed = client.get("/api/v1/orders", headers={"Authorization": "Bearer buyer-token"})
    assert listed.status_code == 200
    assert listed.get_json() == {"orders": [ORDER]}
    list_service.assert_called_once_with("Bearer buyer-token")

    with patch("app.get_order", return_value=ORDER) as detail_service:
        detail = client.get(f"/api/v1/orders/{ORDER_ID}", headers={"Authorization": "Bearer buyer-token"})
    assert detail.status_code == 200
    assert detail.get_json() == {"order": ORDER}
    detail_service.assert_called_once_with(ORDER_ID, "Bearer buyer-token")

    with patch("app.get_order") as service:
        invalid = client.get("/api/v1/orders/not-a-uuid", headers={"Authorization": "Bearer buyer-token"})
    assert invalid.status_code == 400
    service.assert_not_called()


def test_routing_http_errors_are_returned_without_calling_order_services():
    with patch("app.get_order") as detail, patch("app.get_invoice") as invoice:
        client = app.test_client()
        malformed = client.get("/api/v1/orders/../../etc/passwd", headers={"Authorization": "Bearer buyer-token"})
        missing = client.get("/nonexistent-route")
    assert malformed.status_code == 405
    assert missing.status_code == 404
    detail.assert_not_called()
    invoice.assert_not_called()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("UNAUTHENTICATED", 401),
        ("ORDER_NOT_FOUND", 404),
        ("ADDRESS_REQUIRED", 400),
        ("EMPTY_CART", 422),
        ("PAYMENTS_DISABLED", 503),
        ("PAYMENT_INITIALIZATION_FAILED", 502),
        ("ORDER_NOT_PAYABLE", 422),
    ],
)
def test_core_user_errors_map_to_http_status_and_error_json(code, expected):
    with patch("app.checkout", side_effect=UpstreamError("Core explanation", code)):
        response = app.test_client().post(
            "/api/v1/checkout", json={"shipping_mode": "pickup"},
            headers={"Authorization": "Bearer buyer-token"},
        )
    assert response.status_code == expected
    assert response.get_json()["errors"][0]["code"] == code
    assert response.get_json()["errors"][0]["message"] == "Core explanation"


def test_invoice_forwards_pdf_bytes_and_attachment_headers():
    upstream = MagicMock(status_code=200)
    upstream.headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": "attachment; filename=invoice-9.pdf",
    }
    upstream.iter_content.return_value = iter([b"%PDF-1.4", b" body"])
    with patch("app.get_invoice", return_value=upstream) as service:
        response = app.test_client().get(
            f"/api/v1/orders/{ORDER_ID}/invoice", headers={"Authorization": "Bearer buyer-token"}
        )
    assert response.status_code == 200
    assert response.data == b"%PDF-1.4 body"
    assert response.content_type == "application/pdf"
    assert response.headers["Content-Disposition"] == "attachment; filename=invoice-9.pdf"
    service.assert_called_once_with(ORDER_ID, "Bearer buyer-token")
    upstream.close.assert_called_once()


def test_invoice_invalid_uuid_does_not_call_core_and_preserves_core_404():
    client = app.test_client()
    with patch("app.get_invoice") as service:
        invalid = client.get("/api/v1/orders/not-a-uuid/invoice", headers={"Authorization": "Bearer buyer-token"})
        traversal = client.get("/api/v1/orders/%2e%2e%2fsecret/invoice", headers={"Authorization": "Bearer buyer-token"})
    assert invalid.status_code == 400
    assert traversal.status_code == 405
    service.assert_not_called()

    upstream = MagicMock(status_code=404)
    upstream.headers = {"Content-Type": "text/html"}
    upstream.content = b"not found"
    with patch("app.get_invoice", return_value=upstream):
        missing = client.get(f"/api/v1/orders/{ORDER_ID}/invoice", headers={"Authorization": "Bearer buyer-token"})
    assert missing.status_code == 404
    assert missing.data == b"not found"


def _graphql_order():
    return {
        "id": ORDER_ID, "status": "paid", "total": 25.0, "currency": "ARS",
        "shippingMode": "standard", "recipient": "Buyer", "street": "1 Main St",
        "city": "Buenos Aires", "postalCode": "1000", "phone": None,
        "paymentStatus": "approved", "paymentStatusDetail": "accredited",
        "createdAt": "2026-10-20T10:00:00+00:00", "paidAt": "2026-10-20T10:05:00+00:00",
        "lines": [{"bggId": 7, "name": "Game", "unitPrice": 12.5, "quantity": 2, "subtotal": 25.0}],
        "invoice": {"number": 9, "issuedAt": "2026-10-20T10:05:00+00:00", "total": 25.0},
    }


def test_checkout_proxy_uses_core_contract_maps_order_and_forwards_bearer():
    response = MagicMock()
    response.json.return_value = {"data": {"checkout": {
        "order": _graphql_order(), "initPoint": "https://pay.example/1", "userErrors": [],
    }}}
    address = {"recipient": "Buyer", "street": "1 Main St", "city": "Buenos Aires", "postal_code": "1000", "phone": None}
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = checkout("standard", address, "Bearer buyer-token")
    assert result["init_point"] == "https://pay.example/1"
    assert result["order"]["payment_status_detail"] == "accredited"
    assert result["order"]["invoice"]["number"] == 9
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer buyer-token"}
    assert post.call_args.kwargs["json"]["variables"] == {
        "shippingMode": "STANDARD",
        "address": {"recipient": "Buyer", "street": "1 Main St", "city": "Buenos Aires", "postalCode": "1000", "phone": None},
    }
    assert "checkout" in post.call_args.kwargs["json"]["query"]


def test_order_proxy_operations_use_authenticated_graphql_fields():
    response = MagicMock()
    response.json.return_value = {"data": {"retryPayment": {
        "order": _graphql_order(), "initPoint": "https://pay.example/2", "userErrors": [],
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        retry_payment(ORDER_ID, "Bearer buyer-token")
    assert post.call_args.kwargs["json"]["variables"] == {"orderId": ORDER_ID}
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer buyer-token"}

    response.json.return_value = {"data": {"myOrders": [_graphql_order()]}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = get_orders("Bearer buyer-token")
    assert result[0]["payment_status_detail"] == "accredited"
    assert "myOrders" in post.call_args.kwargs["json"]["query"]
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer buyer-token"}

    response.json.return_value = {"data": {"myOrder": _graphql_order()}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        assert get_order(ORDER_ID, "Bearer buyer-token")["id"] == ORDER_ID
    assert post.call_args.kwargs["json"]["variables"] == {"id": ORDER_ID}


def test_core_invoice_proxy_authenticates_then_forwards_validated_id_and_token():
    auth_response = MagicMock()
    auth_response.json.return_value = {"data": {"myOrders": []}}
    invoice_response = MagicMock(status_code=200)
    invoice_response.headers = {"Content-Type": "application/pdf"}
    with patch("src.proxy.requests.post", return_value=auth_response) as post, patch(
        "src.proxy.requests.get", return_value=invoice_response
    ) as get:
        assert get_invoice(ORDER_ID, "Bearer buyer-token") is invoice_response
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer buyer-token"}
    assert "myOrders { id }" in post.call_args.kwargs["json"]["query"]
    get.assert_called_once_with(
        f"http://localhost:8000/invoices/{ORDER_ID}/",
        headers={"Authorization": "Bearer buyer-token"},
        timeout=30,
        stream=True,
    )


def test_core_invoice_proxy_rejects_unsafe_uuid_before_network_calls():
    with patch("src.proxy.requests.post") as post, patch("src.proxy.requests.get") as get:
        with pytest.raises(ValueError):
            get_invoice("../../invoice", "Bearer buyer-token")
    post.assert_not_called()
    get.assert_not_called()


def test_core_invoice_proxy_maps_invalid_bearer_to_401_error():
    auth_response = MagicMock()
    auth_response.json.return_value = {"errors": [{"message": "Authentication is required."}]}
    with patch("src.proxy.requests.post", return_value=auth_response), patch("src.proxy.requests.get") as get:
        with pytest.raises(UpstreamError) as error:
            get_invoice(ORDER_ID, "Bearer invalid")
    assert error.value.code == "UNAUTHENTICATED"
    get.assert_not_called()


def test_unrecognized_core_user_error_is_validation_4xx_with_field():
    error = UpstreamError("Core validation detail", "NEW_VALIDATION_CODE", ["address"], user_error=True)
    with patch("app.checkout", side_effect=error):
        response = app.test_client().post(
            "/api/v1/checkout", json={"shipping_mode": "pickup"},
            headers={"Authorization": "Bearer buyer-token"},
        )
    assert response.status_code == 400
    assert response.get_json()["errors"] == [{
        "code": "NEW_VALIDATION_CODE", "message": "Core validation detail", "field": ["address"],
    }]


def test_core_order_user_errors_are_preserved_as_upstream_error_codes():
    response = MagicMock()
    response.json.return_value = {"data": {"checkout": {
        "order": None, "initPoint": None, "userErrors": [{
            "code": "PAYMENTS_DISABLED", "field": None, "message": "Payments are disabled.",
        }],
    }}}
    with patch("src.proxy.requests.post", return_value=response):
        with pytest.raises(UpstreamError) as error:
            checkout("pickup", None, "Bearer buyer-token")
    assert error.value.code == "PAYMENTS_DISABLED"
    assert str(error.value) == "Payments are disabled."
