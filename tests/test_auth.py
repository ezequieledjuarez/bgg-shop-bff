from unittest.mock import MagicMock, patch
import traceback

import pytest
import requests

from app import app
from src.proxy import UpstreamError, _auth_request, authenticate_account, register_account


VALID_USER = {
    "id": "1",
    "email": "player@example.test",
    "first_name": "Test",
    "last_name": "Player",
    "is_active": True,
}
VALID_SESSION = {
    "access_token": "access-token",
    "refresh_token": "refresh-token",
    "csrf_token": None,
}


@pytest.mark.parametrize("failure", ["timeout", "graphql", "response"])
def test_auth_transport_never_logs_passwords_or_upstream_details(failure, capsys, caplog):
    secret = "synthetic-private-password"
    response = MagicMock()
    response.text = secret
    response.json.return_value = {"errors": [{"message": secret}]} if failure == "graphql" else {"data": {"products": []}}
    caplog.set_level("INFO")
    with patch("builtins.open", create=True) as file_open, \
            patch("requests.post", side_effect=requests.Timeout(secret) if failure == "timeout" else None, return_value=response):
        if failure == "response":
            _auth_request("query products { products }", {"password": secret})
        else:
            with pytest.raises(UpstreamError) as raised:
                _auth_request("query products { products }", {"password": secret})
            assert secret not in "".join(traceback.format_exception(raised.value))
        UpstreamError("generic", response_text=secret)
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + caplog.text + str(file_open.mock_calls)


def test_register_returns_created_account_without_session():
    with patch("app.register_account", return_value={"user": VALID_USER}):
        response = app.test_client().post(
            "/api/v1/auth/register",
            json={
                "email": "player@example.test",
                "password": "safe-password",
                "first_name": "Test",
                "last_name": "Player",
            },
        )

    assert response.status_code == 201
    assert response.get_json() == {"user": VALID_USER}


def test_login_returns_account_and_session():
    with patch(
        "app.authenticate_account",
        return_value={"user": VALID_USER, "session": VALID_SESSION},
    ):
        response = app.test_client().post(
            "/api/v1/auth/login",
            json={"email": "player@example.test", "password": "safe-password"},
        )

    assert response.status_code == 200
    assert response.get_json()["session"] == VALID_SESSION


def test_auth_rejects_non_object_json():
    response = app.test_client().post(
        "/api/v1/auth/login",
        data="[]",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "INVALID"


def test_auth_maps_duplicate_email_to_conflict():
    with patch(
        "app.register_account",
        side_effect=UpstreamError("internal duplicate details", "EMAIL_EXISTS"),
    ):
        response = app.test_client().post(
            "/api/v1/auth/register",
            json={
                "email": "player@example.test",
                "password": "safe-password",
                "first_name": "Test",
                "last_name": "Player",
            },
        )

    assert response.status_code == 409
    assert response.get_json()["errors"][0]["code"] == "EMAIL_EXISTS"
    assert "internal duplicate details" not in response.get_data(as_text=True)


def test_auth_maps_core_duplicate_email_code_to_conflict():
    with patch(
        "app.register_account",
        side_effect=UpstreamError("duplicate", "DUPLICATE_EMAIL"),
    ):
        response = app.test_client().post(
            "/api/v1/auth/register",
            json={
                "email": "player@example.test",
                "password": "safe-password",
                "first_name": "Test",
                "last_name": "Player",
            },
        )

    assert response.status_code == 409


def test_auth_maps_invalid_credentials_to_unauthorized():
    with patch(
        "app.authenticate_account",
        side_effect=UpstreamError("internal credential details", "INVALID_CREDENTIALS"),
    ):
        response = app.test_client().post(
            "/api/v1/auth/login",
            json={"email": "player@example.test", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert response.get_json()["errors"][0]["message"] == "Invalid email or password."
    assert "internal credential details" not in response.get_data(as_text=True)


def test_auth_hides_unexpected_upstream_details():
    with patch(
        "app.authenticate_account",
        side_effect=UpstreamError("database password leaked", "UPSTREAM_ERROR"),
    ):
        response = app.test_client().post(
            "/api/v1/auth/login",
            json={"email": "player@example.test", "password": "safe-password"},
        )

    assert response.status_code == 502
    assert response.get_json() == {"error": "upstream GraphQL request failed"}
    assert "database password leaked" not in response.get_data(as_text=True)


def test_register_proxy_adapts_rest_input_to_graphql_without_returning_password():
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "register": {
                "user": {
                    "id": "1",
                    "email": "player@example.test",
                    "firstName": "Test",
                    "lastName": "Player",
                    "isActive": True,
                },
                "tokens": None,
                "errors": [],
            }
        }
    }
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = register_account({
            "email": " player@example.test ",
            "password": "safe-password",
            "first_name": "Test",
            "last_name": "Player",
        })

    assert result == {"user": VALID_USER}
    variables = post.call_args.kwargs["json"]["variables"]
    assert variables["input"] == {
        "email": "player@example.test",
        "password": "safe-password",
        "firstName": "Test",
        "lastName": "Player",
    }
    assert "password" not in result


def test_login_proxy_requires_tokens():
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "login": {
                "user": {
                    "id": "1",
                    "email": "player@example.test",
                    "firstName": "Test",
                    "lastName": "Player",
                    "isActive": True,
                },
                "tokens": None,
                "errors": [],
            }
        }
    }
    with patch("src.proxy.requests.post", return_value=response):
        try:
            authenticate_account({
                "email": "player@example.test",
                "password": "safe-password",
            })
        except UpstreamError as exc:
            assert "no session" in str(exc)
        else:
            raise AssertionError("authenticate_account accepted a response without tokens")
