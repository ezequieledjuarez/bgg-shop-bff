from unittest.mock import MagicMock, patch

import pytest

from app import app
from src import opkey_middleware
from src.proxy import UpstreamError


@pytest.fixture(autouse=True)
def avoid_request_file_logging(monkeypatch):
    monkeypatch.setattr("app._append_incoming_log", lambda entry: None)


def _identity(*, active=True, staff=False, superuser=False):
    return {
        "data": {
            "me": {
                "isActive": active,
                "isStaff": staff,
                "isSuperuser": superuser,
            }
        }
    }


def _get_current_user(*, authorization="Bearer synthetic-access-token", op_key=None):
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    if op_key is not None:
        headers["X-Op-Key"] = op_key
    return app.test_client().get("/api/v1/auth/me", headers=headers)


@pytest.mark.parametrize(
    ("core_identity", "expected"),
    [
        (_identity(staff=True), {"is_staff": True, "is_superuser": False}),
        (_identity(superuser=True), {"is_staff": False, "is_superuser": True}),
        (_identity(), {"is_staff": False, "is_superuser": False}),
    ],
)
def test_current_user_returns_only_current_role_flags(core_identity, expected):
    with patch("src.proxy._graphql_request", return_value=core_identity) as graphql:
        response = _get_current_user()

    assert response.status_code == 200
    assert response.get_json() == expected
    assert response.headers["Cache-Control"] == "no-store"
    query = graphql.call_args.args[0]
    assert "me { isActive isStaff isSuperuser }" in " ".join(query.split())
    assert " email " not in query and " id " not in query
    assert graphql.call_args.args[2] == "Bearer synthetic-access-token"


@pytest.mark.parametrize(
    "authorization",
    [None, "", "   ", "Basic synthetic-token", "Bearer", "Bearer   ", "Bearer one two"],
)
def test_current_user_requires_a_single_nonempty_bearer_credential(authorization):
    with patch("src.proxy._graphql_request") as graphql:
        response = _get_current_user(authorization=authorization)

    assert response.status_code == 401
    assert response.get_json() == {
        "errors": [{"code": "UNAUTHENTICATED", "message": "Authentication is required."}]
    }
    assert response.headers["Cache-Control"] == "no-store"
    graphql.assert_not_called()


@pytest.mark.parametrize("valid", [True, False])
def test_current_user_rejects_operation_key_only_without_validation(valid):
    with patch.object(
        opkey_middleware,
        "validate_op_key_with_core",
        return_value={"valid": valid},
    ) as validate, patch("src.proxy._graphql_request") as graphql:
        response = _get_current_user(authorization=None, op_key="synthetic-operation-key")

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    validate.assert_not_called()
    graphql.assert_not_called()


@pytest.mark.parametrize(
    "core_response",
    [
        {"data": {"me": None}},
        _identity(active=False, staff=True),
        {"errors": [{"message": "Authentication is required.", "extensions": {"code": "UNAUTHENTICATED"}}]},
    ],
)
def test_current_user_maps_missing_invalid_or_inactive_core_identity_to_401(core_response):
    with patch("src.proxy._graphql_request", return_value=core_response):
        response = _get_current_user()

    assert response.status_code == 401
    assert response.get_json() == {
        "errors": [{"code": "UNAUTHENTICATED", "message": "Authentication is required."}]
    }
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "core_response",
    [
        {},
        {"data": {}},
        {"data": {"me": []}},
        {"data": {"me": {"isActive": True, "isStaff": 1, "isSuperuser": False}}},
        {"data": {"me": {"isActive": True, "isStaff": False}}},
        {"data": {"me": {"isActive": "true", "isStaff": False, "isSuperuser": False}}},
        {"errors": [{"message": "database password at https://internal.example.test"}]},
    ],
)
def test_current_user_sanitizes_errors_and_rejects_malformed_core_identity(core_response, caplog):
    with patch("src.proxy._graphql_request", return_value=core_response):
        response = _get_current_user()

    assert response.status_code == 502
    assert response.get_json() == {
        "errors": [{"code": "UPSTREAM_FAILURE", "message": "The current user could not be verified."}]
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert "database password" not in response.get_data(as_text=True) + caplog.text
    assert "https://internal.example.test" not in response.get_data(as_text=True) + caplog.text


def test_current_user_sanitizes_upstream_exception_details(caplog):
    private_details = (
        "private upstream trace at https://core.internal/graphql/"
        "with credential synthetic-secret"
    )
    with patch(
        "src.proxy._graphql_request",
        side_effect=UpstreamError(private_details, context={"trace": private_details}),
    ):
        response = _get_current_user()

    assert response.status_code == 502
    assert response.get_json() == {
        "errors": [{"code": "UPSTREAM_FAILURE", "message": "The current user could not be verified."}]
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert "Current-user identity verification failed." in caplog.text
    assert private_details not in response.get_data(as_text=True) + caplog.text
    assert "synthetic-secret" not in response.get_data(as_text=True) + caplog.text


def test_current_user_proxy_sends_bearer_and_requests_only_approved_core_fields():
    core_response = MagicMock(status_code=200)
    core_response.json.return_value = _identity(staff=True)

    with patch("src.proxy.requests.post", return_value=core_response) as post:
        response = _get_current_user()

    assert response.status_code == 200
    assert response.get_json() == {"is_staff": True, "is_superuser": False}
    assert response.headers["Cache-Control"] == "no-store"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer synthetic-access-token"}
    query = post.call_args.kwargs["json"]["query"]
    assert "isActive" in query and "isStaff" in query and "isSuperuser" in query
    assert "email" not in query and "id" not in query
    assert post.call_args.kwargs["allow_redirects"] is False


def test_current_user_reflects_role_revocation_on_the_next_request():
    with patch(
        "src.proxy._graphql_request",
        side_effect=[_identity(staff=True), _identity()],
    ) as graphql:
        first = _get_current_user()
        second = _get_current_user()

    assert first.status_code == second.status_code == 200
    assert first.get_json() == {"is_staff": True, "is_superuser": False}
    assert second.get_json() == {"is_staff": False, "is_superuser": False}
    assert first.headers["Cache-Control"] == second.headers["Cache-Control"] == "no-store"
    assert graphql.call_count == 2


def test_current_user_responses_are_not_cached_when_handler_fails():
    with patch("src.proxy._graphql_request", side_effect=RuntimeError("private traceback detail")):
        response = _get_current_user()

    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"
    assert b"private traceback detail" not in response.data


def test_current_user_method_errors_are_not_cached():
    response = app.test_client().post("/api/v1/auth/me")

    assert response.status_code == 405
    assert response.headers["Cache-Control"] == "no-store"
