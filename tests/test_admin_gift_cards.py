from unittest.mock import MagicMock, patch

import pytest
import requests
from werkzeug.exceptions import HTTPException

from app import app


PATH = "/api/v1/admin/gift-cards"
TOKEN = "Bearer synthetic-admin-token"
CARD = {
    "id": "11111111-2222-4333-8444-555555555555",
    "code": "a" * 64,
    "amount": "20000.00",
    "currency": "ARS",
}


def response(payload):
    upstream = MagicMock(status_code=200)
    upstream.json.return_value = payload
    return upstream


def test_issuance_requires_bearer():
    with patch("src.controllers.admin_gift_cards_controller.requests.post") as post:
        result = app.test_client().post(PATH, json={"amount": "20000.00"})
    assert result.status_code == 401
    post.assert_not_called()


@pytest.mark.parametrize("body", [{}, {"amount": "0"}, {"amount": "-2"}, {"amount": "1.001"}, {"amount": 20}, {"amount": "20", "extra": 1}])
def test_issuance_rejects_invalid_request(body):
    with patch("src.controllers.admin_gift_cards_controller.requests.post") as post:
        result = app.test_client().post(PATH, json=body, headers={"Authorization": TOKEN})
    assert result.status_code == 400
    post.assert_not_called()


def test_admin_issuance_forwards_bearer_without_logging_secrets(capsys):
    payload = {"data": {"createGiftCard": {"giftCard": CARD, "userErrors": []}}}
    with patch("src.controllers.admin_gift_cards_controller.requests.post", return_value=response(payload)) as post, patch("app._append_incoming_log") as log:
        result = app.test_client().post(PATH, json={"amount": "20000.00"}, headers={"Authorization": TOKEN})
    assert result.status_code == 201
    assert result.get_json() == CARD
    assert result.headers["Cache-Control"] == "no-store"
    assert post.call_args.kwargs["headers"]["Authorization"] == TOKEN
    assert TOKEN not in str(log.call_args_list)
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
    assert CARD["code"] not in captured.out + captured.err


@pytest.mark.parametrize("path", ["/api/v1/credit", "/api/v1/gift-cards/redeem", "/api/v1/checkout/credit"])
@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_gift_card_requests_do_not_log_secrets(path, method):
    with patch.dict(app.error_handler_spec[None][None], {HTTPException: lambda error: error}), patch("app._append_incoming_log") as log:
        app.test_client().open(
            path,
            method=method,
            headers={"Authorization": TOKEN, "X-Gift-Card-Code": CARD["code"]},
            query_string={"secret": "synthetic-query-secret", "code": CARD["code"]},
            json={"code": CARD["code"]},
        )
    log.assert_not_called()


@pytest.mark.parametrize(("code", "status"), [("UNAUTHENTICATED", 401), ("FORBIDDEN", 403), ("INVALID_AMOUNT", 400), ("SERVER_ERROR", 502)])
def test_core_errors_are_sanitized(code, status):
    payload = {"data": {"createGiftCard": {"giftCard": None, "userErrors": [{"code": code, "message": "private upstream detail"}]}}}
    with patch("src.controllers.admin_gift_cards_controller.requests.post", return_value=response(payload)):
        result = app.test_client().post(PATH, json={"amount": "1.00"}, headers={"Authorization": TOKEN})
    assert result.status_code == status
    assert "private upstream detail" not in result.get_data(as_text=True)


def test_upstream_exception_is_sanitized():
    with patch("src.controllers.admin_gift_cards_controller.requests.post", side_effect=requests.Timeout("private upstream detail")):
        result = app.test_client().post(PATH, json={"amount": "1.00"}, headers={"Authorization": TOKEN})
    assert result.status_code == 502
    assert "private upstream detail" not in result.get_data(as_text=True)


def test_invalid_upstream_card_is_sanitized():
    card = {**CARD, "amount": "private upstream detail"}
    payload = {"data": {"createGiftCard": {"giftCard": card, "userErrors": []}}}
    with patch("src.controllers.admin_gift_cards_controller.requests.post", return_value=response(payload)):
        result = app.test_client().post(PATH, json={"amount": "1.00"}, headers={"Authorization": TOKEN})
    assert result.status_code == 502
    assert "private upstream detail" not in result.get_data(as_text=True)