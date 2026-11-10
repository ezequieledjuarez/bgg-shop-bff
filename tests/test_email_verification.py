import hashlib
import json
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from app import app
from src import proxy
from src.proxy import UpstreamError, VerificationError, authenticate_account, register_account, verification_caller

SECRET = "synthetic-internal-secret-0123456789-abcdef"
TOKEN = "A" * 43
CONFIRM = "/api/v1/auth/email-verification/confirm"
RESEND = "/api/v1/auth/email-verification/resend"
USER = {"id": "1", "email": "p@example.test", "firstName": "T", "lastName": "P", "isActive": True}


@pytest.fixture(autouse=True)
def trusted_env():
    with patch.dict("os.environ", {"OPKEY_INTERNAL_SECRET": SECRET}):
        yield


@pytest.fixture
def client():
    return app.test_client()


def core(data, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = data
    return response


def call(client, path, body, **kwargs):
    return client.post(path, json=body, environ_overrides={"REMOTE_ADDR": "203.0.113.9"}, **kwargs)


def test_caller_derives_from_peer_only_and_rejects_unparsable():
    expected = hashlib.sha256(b"email-verification:caller:v1:203.0.113.9").hexdigest()
    assert verification_caller("203.0.113.9") == expected
    for bad in (None, "", "not-an-ip"):
        with pytest.raises(VerificationError) as raised:
            verification_caller(bad)
        assert raised.value.code == "VERIFICATION_UNAVAILABLE"


def test_forwarded_headers_do_not_change_caller(client):
    with patch("requests.post", return_value=core({"data": {"confirmEmailVerification": {
            "verified": True, "message": "ok", "errors": []}}})) as post:
        call(client, CONFIRM, {"token": TOKEN}, headers={"X-Forwarded-For": "198.51.100.1", "Forwarded": "for=198.51.100.2"})
    sent = post.call_args.kwargs["headers"]
    assert sent["X-Verification-Caller"] == verification_caller("203.0.113.9")
    assert sent["X-Internal-Secret"] == SECRET
    assert post.call_args.kwargs["allow_redirects"] is False


def test_confirm_success_is_explicit_post_without_credentials(client):
    with patch("requests.post", return_value=core({"data": {"confirmEmailVerification": {
            "verified": True, "message": "Verified", "errors": []}}})) as post:
        response = call(client, CONFIRM, {"token": TOKEN})
    assert response.status_code == 200
    assert response.get_json() == {"verified": True, "message": "Verified"}
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Set-Cookie" not in response.headers
    assert post.call_args.kwargs["json"]["variables"] == {"input": {"token": TOKEN}}


@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
@pytest.mark.parametrize("path", [CONFIRM, RESEND])
def test_non_post_never_reaches_core(client, method, path):
    with patch("requests.post") as post:
        response = getattr(client, method)(path + "?token=" + TOKEN, environ_overrides={"REMOTE_ADDR": "203.0.113.9"})
    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"
    assert response.headers["Cache-Control"] == "no-store"
    post.assert_not_called()


@pytest.mark.parametrize("body", [
    None, {}, [], {"token": None}, {"token": "short"}, {"token": TOKEN, "extra": 1},
    {"token": 7}, {"token": []}, {"token": {"nested": TOKEN}}, {"token": "!" * 43},
    {"token": "A" * 100000}, {"token": TOKEN + "\n"},
])
def test_malformed_confirm_counts_at_core_with_bounded_safe_input(client, body):
    with patch("requests.post", return_value=core({"data": {"confirmEmailVerification": {
            "verified": False, "errors": [{"code": "INVALID_VERIFICATION_TOKEN"}]}}})) as post:
        response = call(client, CONFIRM, body)
    assert response.status_code == 400
    assert response.get_json() == {"errors": [{"code": "INVALID_VERIFICATION_TOKEN",
                                              "message": "This verification link is invalid or has expired."}]}
    post.assert_called_once()
    assert post.call_args.kwargs["json"]["variables"] == {"input": {"token": ""}}
    assert post.call_args.kwargs["headers"]["X-Verification-Caller"] == verification_caller("203.0.113.9")


def test_malformed_confirm_preserves_core_caller_quota_response(client):
    with patch("requests.post", return_value=core({"data": {"confirmEmailVerification": {
            "verified": False, "errors": [{"code": "RATE_LIMITED", "retryAfterSeconds": 900}]}}})) as post:
        response = call(client, CONFIRM, {"token": {"untrusted": "A" * 100000}})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "900"
    assert response.get_json()["retry_after_seconds"] == 900
    assert post.call_args.kwargs["json"]["variables"] == {"input": {"token": ""}}
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_unusable_token_maps_to_same_generic_400(client):
    with patch("requests.post", return_value=core({"data": {"confirmEmailVerification": {
            "verified": False, "message": None,
            "errors": [{"code": "INVALID_VERIFICATION_TOKEN", "retryAfterSeconds": None}]}}})):
        response = call(client, CONFIRM, {"token": TOKEN})
    assert response.status_code == 400
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert TOKEN not in response.get_data(as_text=True)


def test_rate_limit_maps_to_429_with_retry_after(client):
    with patch("requests.post", return_value=core({"data": {"resendEmailVerification": {
            "message": None, "errors": [{"code": "RATE_LIMITED", "retryAfterSeconds": 120}]}}})):
        response = call(client, RESEND, {"email": "p@example.test"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "120"
    assert response.get_json()["retry_after_seconds"] == 120


def test_invalid_retry_after_from_core_fails_closed(client):
    with patch("requests.post", return_value=core({"data": {"resendEmailVerification": {
            "message": None, "errors": [{"code": "RATE_LIMITED", "retryAfterSeconds": 0}]}}})):
        response = call(client, RESEND, {"email": "p@example.test"})
    assert response.status_code == 502


def test_resend_is_neutral_and_normalizes_email(client):
    with patch("requests.post", return_value=core({"data": {"resendEmailVerification": {
            "message": "If the account is pending, a new link was sent.", "errors": []}}})) as post:
        response = call(client, RESEND, {"email": "  P@Example.TEST "})
    assert response.status_code == 202
    assert response.get_json() == {"message": "If the account is pending, a new link was sent."}
    assert post.call_args.kwargs["json"]["variables"] == {"input": {"email": "p@example.test"}}


@pytest.mark.parametrize("email", ["", "no-at", 5, "a@b" + "c" * 260])
def test_resend_invalid_email_is_400_without_echo(client, email):
    with patch("requests.post") as post:
        response = call(client, RESEND, {"email": email})
    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "INVALID"
    assert str(email) not in response.get_data(as_text=True) or email == ""
    post.assert_not_called()


@pytest.mark.parametrize("secret", ["", "short"])
def test_missing_or_weak_trust_secret_is_503_without_core_call(client, secret):
    with patch.dict("os.environ", {"OPKEY_INTERNAL_SECRET": secret}), patch("requests.post") as post:
        response = call(client, CONFIRM, {"token": TOKEN})
    assert response.status_code == 503
    assert response.get_json()["errors"][0]["code"] == "VERIFICATION_UNAVAILABLE"
    post.assert_not_called()


def test_unparsable_peer_is_503_without_core_call(client):
    with patch("requests.post") as post:
        response = client.post(CONFIRM, json={"token": TOKEN}, environ_overrides={"REMOTE_ADDR": "garbage"})
    assert response.status_code == 503
    post.assert_not_called()


@pytest.mark.parametrize("code", ["VERIFICATION_UNAVAILABLE", "FORBIDDEN"])
def test_core_unavailable_and_untrusted_map_to_503(client, code):
    with patch("requests.post", return_value=core({"data": {"confirmEmailVerification": {
            "verified": False, "message": None, "errors": [{"code": code, "retryAfterSeconds": None}]}}})):
        response = call(client, CONFIRM, {"token": TOKEN})
    assert response.status_code == 503
    assert response.get_json()["errors"][0]["code"] == "VERIFICATION_UNAVAILABLE"


@pytest.mark.parametrize("failure", ["timeout", "status", "json", "graphql", "shape"])
def test_transport_and_shape_failures_are_sanitized_502(client, failure, caplog):
    leak = "synthetic-leak-http://core.internal/db-password"
    caplog.set_level(logging.INFO)
    bad = core({"errors": [{"message": leak}]} if failure == "graphql" else {"data": {"x": 1}},
               status=500 if failure == "status" else 200)
    if failure == "json":
        bad.json.side_effect = ValueError(leak)
    effect = requests.Timeout(leak) if failure == "timeout" else None
    with patch("requests.post", side_effect=effect, return_value=bad):
        response = call(client, CONFIRM, {"token": TOKEN})
    assert response.status_code == 502
    text = response.get_data(as_text=True) + caplog.text
    assert leak not in text and TOKEN not in text and SECRET not in text
    assert response.headers["Cache-Control"] == "no-store"


def test_register_returns_pending_verification_without_session(client):
    data = {"data": {"register": {"user": USER, "verification": {
        "state": "PENDING", "deliveryStatus": "SUBMITTED", "message": "Check your email."}, "errors": []}}}
    with patch("requests.post", return_value=core(data)) as post:
        response = client.post("/api/v1/auth/register", json={
            "email": "P@example.test", "password": "Synthetic-password-123!", "first_name": "T", "last_name": "P"})
    assert response.status_code == 201
    body = response.get_json()
    assert body["verification"] == {"state": "PENDING", "delivery_status": "SUBMITTED", "message": "Check your email."}
    assert "session" not in body
    assert "tokens" not in post.call_args.kwargs["json"]["query"]
    assert "verification" in post.call_args.kwargs["json"]["query"]


def test_login_not_verified_is_403_without_cookies_and_keeps_guest_cart(client):
    data = {"data": {"login": {"user": None, "tokens": None, "errors": [
        {"field": None, "code": "EMAIL_NOT_VERIFIED", "message": "x"}]}}}
    client.set_cookie("cart_id", "guest-cart", domain="localhost")
    with patch("requests.post", return_value=core(data)):
        response = client.post("/api/v1/auth/login", json={"email": "p@example.test", "password": "password123"})
    assert response.status_code == 403
    assert response.get_json() == {"errors": [{"code": "EMAIL_NOT_VERIFIED", "message": "Verify your email before signing in."}]}
    assert not response.headers.getlist("Set-Cookie")
    assert response.headers["Cache-Control"] == "no-store"


def test_login_code_is_distinct_from_invalid_credentials():
    data = {"data": {"login": {"user": None, "tokens": None, "errors": [{"code": "EMAIL_NOT_VERIFIED"}]}}}
    with patch("requests.post", return_value=core(data)), pytest.raises(UpstreamError) as raised:
        authenticate_account({"email": "p@example.test", "password": "password123"})
    assert raised.value.code == "EMAIL_NOT_VERIFIED"


def test_register_account_helper_rejects_short_password():
    with pytest.raises(ValueError):
        register_account({"email": "p@example.test", "password": "x", "first_name": "T", "last_name": "P"})


def test_token_never_logged_on_success_or_failure(client, caplog):
    caplog.set_level(logging.DEBUG)
    with patch("requests.post", side_effect=requests.ConnectionError(TOKEN)):
        call(client, CONFIRM, {"token": TOKEN})
    assert TOKEN not in caplog.text
    assert json.dumps(proxy.VERIFICATION_TOKEN_PATTERN.pattern)
