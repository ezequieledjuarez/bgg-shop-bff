from unittest.mock import Mock, patch

import pytest

from app import app
from src.proxy import UpstreamError


USERS_URL = "/api/v1/admin/users"
PRIVILEGES_URL = f"{USERS_URL}/target-user/privileges"
BEARER = "Bearer synthetic-admin-token"
AUTH = {"Authorization": BEARER}
SAFE_USER = {
    "id": "target-user",
    "email": "target@example.test",
    "first_name": "Target",
    "last_name": "User",
    "is_active": True,
    "is_staff": False,
    "is_superuser": True,
}


def _users_response(user=None):
    user = user or SAFE_USER
    return {
        "data": {
            "adminUsers": {
                "items": [user],
                "nextCursor": "opaque-next-page",
            }
        }
    }


def _mutation_response(user, user_errors=None):
    return {
        "data": {
            "adminUpdateUserPrivilege": {
                "user": user,
                "userErrors": user_errors or [],
            }
        }
    }


def _core_forbidden_error():
    return {
        "errors": [{
            "message": "Superuser permission is required.",
            "extensions": {"code": "FORBIDDEN"},
        }]
    }


def _core_unauthenticated_error():
    return {
        "errors": [{
            "message": "Authentication is required.",
            "extensions": {"code": "UNAUTHENTICATED"},
        }]
    }


def _find_call(calls, operation):
    return next(call for call in calls if operation in call.args[0])


@pytest.mark.parametrize(
    ("method", "path", "json_body", "operation"),
    [
        ("GET", USERS_URL, None, "adminUsers"),
        (
            "PATCH",
            PRIVILEGES_URL,
            {"privilege": "is_staff", "enabled": True},
            "adminUpdateUserPrivilege",
        ),
    ],
    ids=("inactive-list", "inactive-update"),
)
def test_inactive_bearer_uses_core_forbidden_response(
    method, path, json_body, operation
):
    def core_response(query, variables, token):
        assert operation in query
        assert "WhoAmI" not in query
        assert token == BEARER
        if operation == "adminUsers":
            return _core_forbidden_error()
        return _mutation_response(
            None,
            [{
                "code": "FORBIDDEN",
                "field": None,
                "message": "Superuser permission is required.",
            }],
        )

    with patch("src.proxy._graphql_request", side_effect=core_response) as graphql:
        response = app.test_client().open(
            path,
            method=method,
            json=json_body,
            headers=AUTH,
        )

    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    assert len(graphql.call_args_list) == 1


def test_user_listing_forwards_bearer_and_filters():
    upstream_user = {
        **SAFE_USER,
        "is_active": False,
        "password": "synthetic-password",
        "access_token": "synthetic-access-token",
    }
    listed_user = {**SAFE_USER, "is_active": False}
    with patch("src.proxy._graphql_request", return_value=_users_response(upstream_user)) as graphql:
        response = app.test_client().get(
            USERS_URL,
            query_string={"search": "Target", "cursor": "opaque-cursor", "limit": 25},
            headers=AUTH,
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [listed_user],
        "next_cursor": "opaque-next-page",
    }
    assert response.headers["Cache-Control"] == "no-store"
    list_call = _find_call(graphql.call_args_list, "adminUsers")
    assert list_call.args[2] == BEARER
    assert list_call.args[1] == {
        "search": "Target",
        "cursor": "opaque-cursor",
        "limit": 25,
    }


@pytest.mark.parametrize(
    ("privilege", "enabled", "saved_user"),
    [
        ("is_staff", True, {**SAFE_USER, "is_staff": True, "is_superuser": False}),
        ("is_superuser", True, {**SAFE_USER, "is_staff": False, "is_superuser": True}),
    ],
)
def test_privilege_patch_changes_only_the_selected_flag_and_propagates_bearer(
    privilege, enabled, saved_user
):
    with patch(
        "src.proxy._graphql_request",
        return_value=_mutation_response(saved_user),
    ) as graphql:
        response = app.test_client().patch(
            PRIVILEGES_URL,
            json={"privilege": privilege, "enabled": enabled},
            headers=AUTH,
        )

    assert response.status_code == 200
    assert response.get_json() == saved_user
    assert response.headers["Cache-Control"] == "no-store"
    mutation_call = _find_call(graphql.call_args_list, "adminUpdateUserPrivilege")
    assert mutation_call.args[2] == BEARER
    assert mutation_call.args[1] == {
        "userId": "target-user",
        "privilege": privilege,
        "enabled": enabled,
    }


@pytest.mark.parametrize(
    ("payload", "method", "path", "operation"),
    [
        (_core_forbidden_error(), "GET", USERS_URL, "adminUsers"),
        (
            _mutation_response(
                None,
                [{
                    "code": "FORBIDDEN",
                    "field": None,
                    "message": "Superuser permission is required.",
                }],
            ),
            "PATCH",
            PRIVILEGES_URL,
            "adminUpdateUserPrivilege",
        ),
    ],
    ids=("staff-only-list", "inactive-superuser-update"),
)
def test_core_denials_are_mapped_without_identity_preflight(payload, method, path, operation):
    with patch("src.proxy._graphql_request", return_value=payload) as graphql:
        response = app.test_client().open(
            path,
            method=method,
            json={"privilege": "is_staff", "enabled": True} if method == "PATCH" else None,
            headers=AUTH,
        )

    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    assert len(graphql.call_args_list) == 1
    assert operation in graphql.call_args[0][0]
    assert graphql.call_args[0][2] == BEARER


def test_user_listing_requires_bearer_authentication():
    with patch(
        "src.proxy._graphql_request",
        return_value=_core_unauthenticated_error(),
    ) as graphql:
        response = app.test_client().get(USERS_URL)

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert len(graphql.call_args_list) == 1
    assert "adminUsers" in graphql.call_args[0][0]
    assert graphql.call_args[0][2] is None


def test_missing_bearer_cannot_update_user_privileges():
    with patch(
        "src.proxy._graphql_request",
        return_value=_mutation_response(
            None,
            [{
                "code": "UNAUTHENTICATED",
                "field": None,
                "message": "Authentication is required.",
            }],
        ),
    ) as graphql:
        response = app.test_client().patch(
            PRIVILEGES_URL,
            json={"privilege": "is_staff", "enabled": True},
        )

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert len(graphql.call_args_list) == 1
    assert "adminUpdateUserPrivilege" in graphql.call_args[0][0]
    assert graphql.call_args[0][2] is None


def test_invalid_bearer_cannot_list_users():
    with patch(
        "src.proxy._graphql_request",
        return_value=_core_unauthenticated_error(),
    ) as graphql:
        response = app.test_client().get(
            USERS_URL,
            headers={"Authorization": "Bearer synthetic-invalid-token"},
        )

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert len(graphql.call_args_list) == 1
    assert "adminUsers" in graphql.call_args[0][0]
    assert graphql.call_args[0][2] is not None


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", USERS_URL, None),
        ("PATCH", PRIVILEGES_URL, {"privilege": "is_staff", "enabled": True}),
    ],
    ids=("list", "update"),
)
def test_operation_key_alone_cannot_list_or_change_users(method, path, json_body):
    with patch(
        "src.opkey_middleware.validate_op_key_with_core",
        return_value={"valid": True, "user_id": "actor-user"},
    ), patch("src.proxy._graphql_request") as graphql:
        response = app.test_client().open(
            path,
            method=method,
            json=json_body,
            headers={"X-Op-Key": "synthetic-operation-key"},
        )

    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    graphql.assert_not_called()


def test_bearer_personnel_request_does_not_forward_operation_key():
    upstream_response = Mock()
    upstream_response.raise_for_status.return_value = None
    upstream_response.json.return_value = _users_response()
    with patch(
        "src.opkey_middleware.validate_op_key_with_core",
        return_value={"valid": True, "user_id": "actor-user"},
    ), patch(
        "src.proxy.requests.post",
        return_value=upstream_response,
    ) as post, patch.dict("os.environ", {"OPKEY_INTERNAL_SECRET": "x" * 32}):
        response = app.test_client().get(
            USERS_URL,
            headers={
                **AUTH,
                "X-Op-Key": "synthetic-operation-key",
            },
        )

    assert response.status_code == 200
    assert post.call_args.kwargs["headers"] == {"Authorization": BEARER}


def test_last_active_superuser_error_is_conflict_and_excludes_upstream_detail():
    private_upstream_detail = "synthetic database constraint and internal trace"
    with patch(
        "src.proxy._graphql_request",
        return_value=_mutation_response(
            None,
            [
                {
                    "code": "LAST_ACTIVE_SUPERUSER",
                    "field": "enabled",
                    "message": private_upstream_detail,
                }
            ],
        ),
    ):
        response = app.test_client().patch(
            PRIVILEGES_URL,
            json={"privilege": "is_superuser", "enabled": False},
            headers=AUTH,
        )

    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    error = response.get_json()["errors"][0]
    assert error["code"] == "LAST_ACTIVE_SUPERUSER"
    assert error["message"]
    assert private_upstream_detail not in response.get_data(as_text=True)


def test_upstream_exception_is_sanitized_for_user_listing():
    private_upstream_detail = "synthetic upstream URL, credential, and stack trace"
    with patch(
        "src.proxy._graphql_request",
        side_effect=UpstreamError(private_upstream_detail),
    ):
        response = app.test_client().get(USERS_URL, headers=AUTH)

    assert response.status_code == 502
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["error"]
    assert private_upstream_detail not in response.get_data(as_text=True)
