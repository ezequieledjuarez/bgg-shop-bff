import json
from unittest.mock import patch

import src.services as services
from src.proxy import UpstreamError
import requests


class DummyResponse:
    def __init__(self, json_obj, status_code=200):
        self._json = json_obj
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP error")


def capture_post(expected_checks):
    """Return a function suitable to patch `requests.post` that captures the JSON body and
    returns a minimal GraphQL-shaped response matching the called operation.
    expected_checks: list of callables(json_body)->None assertions
    """

    def _inner(url, json=None, headers=None, timeout=None):
        body = json or {}
        for check in expected_checks:
            check(body)
        # Minimal success payload echoing the fields
        data_field = None
        if isinstance(body.get("query"), str):
            q = body["query"]
            if "addToCart" in q:
                data_field = {"addToCart": {"cart": {"cartId": body["variables"].get("cartId", "c1"), "subtotal": 100, "lines": []}}}
            elif "applyCouponPreview" in q:
                data_field = {"applyCouponPreview": {"valid": True, "discountAmount": 5.0, "newTotal": 95.0, "userErrors": []}}
            else:
                data_field = {"ok": True}
        else:
            data_field = {"ok": True}
        return DummyResponse({"data": data_field})

    return _inner


def test_add_to_cart_sends_expected_graphql_shape():
    def check(body):
        assert "query" in body and "addToCart" in body["query"]
        vars = body.get("variables") or {}
        assert vars.get("bggId") == 123
        assert vars.get("quantity") == 2

    with patch("src.proxy.requests.post", side_effect=capture_post([check])):
        res = services.add_to_cart(123, 2, cart_id="cart-xyz")
        assert isinstance(res, dict)


def test_apply_coupon_preview_graphql_shape():
    def check(body):
        assert "query" in body and "applyCouponPreview" in body["query"]
        vars = body.get("variables") or {}
        assert vars.get("code") == "SUMMER"

    with patch("src.proxy.requests.post", side_effect=capture_post([check])):
        res = services.admin_apply_coupon_preview("SUMMER", cart_id="cart-1")
        assert res.get("valid") is True


def test_apply_coupon_preview_user_errors_raises():
    def check(body):
        assert "query" in body and "applyCouponPreview" in body["query"]

    def user_error_post(url, json=None, headers=None, timeout=None):
        # Return a payload with userErrors
        return DummyResponse({
            "data": {"applyCouponPreview": {"valid": False, "discountAmount": 0.0, "newTotal": 100.0, "userErrors": [{"field": "code", "code": "INVALID_COUPON", "message": "Coupon invalid"}]}}
        })

    with patch("src.proxy.requests.post", side_effect=user_error_post):
        try:
            services.admin_apply_coupon_preview("BAD", cart_id="cart-1")
            assert False, "Expected UpstreamError"
        except UpstreamError as e:
            assert e.user_error is True


def test_add_to_cart_http_error_raises():
    # Simulate network/request exception
    def error_post(url, json=None, headers=None, timeout=None):
        raise requests.RequestException("boom")

    with patch("src.proxy.requests.post", side_effect=error_post):
        try:
            services.add_to_cart(1, 1, cart_id="c1")
            assert False, "Expected UpstreamError"
        except UpstreamError:
            pass
