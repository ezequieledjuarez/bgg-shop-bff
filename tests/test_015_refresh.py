from unittest.mock import MagicMock, patch

import pytest
import requests

from app import app


def _client_with_refresh_cookie():
    client = app.test_client()
    client.set_cookie("refresh_token", "synthetic-refresh-token")
    return client


def _assert_refresh_preserved(response):
    assert "Max-Age=0" not in response.headers.get("Set-Cookie", "")
    assert response.headers["Cache-Control"] == "no-store"


def test_refresh_upstream_503_is_gateway_error_and_preserves_cookie():
    upstream = MagicMock(status_code=503)
    with patch("app._requests.post", return_value=upstream) as post:
        response = _client_with_refresh_cookie().post("/api/v1/auth/refresh")

    assert response.status_code == 502
    assert response.get_json() == {"detail": "refresh upstream error"}
    _assert_refresh_preserved(response)
    assert post.call_args.kwargs["allow_redirects"] is False


def test_refresh_upstream_401_rejects_and_clears_cookie():
    with patch("app._requests.post", return_value=MagicMock(status_code=401)):
        response = _client_with_refresh_cookie().post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert "Max-Age=0" in response.headers["Set-Cookie"]


@pytest.mark.parametrize(
    "json_result",
    [None, [], {}, {"access_token": 42}, {"access_token": "valid-access", "refresh_token": 42}],
)
def test_refresh_invalid_upstream_payload_is_sanitized_and_preserves_cookie(json_result):
    upstream = MagicMock(status_code=200)
    upstream.json.return_value = json_result
    with patch("app._requests.post", return_value=upstream):
        response = _client_with_refresh_cookie().post("/api/v1/auth/refresh")

    assert response.status_code == 502
    assert response.get_json() == {"detail": "invalid upstream response"}
    _assert_refresh_preserved(response)


def test_refresh_invalid_upstream_json_is_sanitized_and_preserves_cookie():
    upstream = MagicMock(status_code=200)
    upstream.json.side_effect = ValueError("synthetic private body")
    with patch("app._requests.post", return_value=upstream):
        response = _client_with_refresh_cookie().post("/api/v1/auth/refresh")

    assert response.status_code == 502
    assert response.get_json() == {"detail": "invalid upstream response"}
    _assert_refresh_preserved(response)
    assert "synthetic private body" not in response.get_data(as_text=True)


def test_refresh_transport_error_is_sanitized_and_preserves_cookie():
    with patch(
        "app._requests.post",
        side_effect=requests.exceptions.Timeout("synthetic private timeout"),
    ):
        response = _client_with_refresh_cookie().post("/api/v1/auth/refresh")

    assert response.status_code == 502
    assert response.get_json() == {"detail": "refresh upstream error"}
    _assert_refresh_preserved(response)


def test_refresh_without_token_is_noncacheable_and_does_not_call_core():
    with patch("app._requests.post") as post:
        response = app.test_client().post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.get_json() == {"detail": "no refresh token"}
    assert response.headers["Cache-Control"] == "no-store"
    assert "Max-Age=0" in response.headers["Set-Cookie"]
    post.assert_not_called()


def test_refresh_upstream_redirect_is_not_followed_or_accepted():
    upstream = MagicMock(status_code=302)
    with patch("app._requests.post", return_value=upstream) as post:
        response = _client_with_refresh_cookie().post("/api/v1/auth/refresh")

    assert response.status_code == 502
    _assert_refresh_preserved(response)
    assert post.call_args.kwargs["allow_redirects"] is False
