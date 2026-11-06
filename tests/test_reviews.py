from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app import app
from src import services
from src.proxy import UpstreamError


MODERATION_QUEUE = "/api/v1/admin/reviews"
MODERATION_ACTION = f"{MODERATION_QUEUE}/501/actions"
MODERATION_AUTH = {"Authorization": "Bearer synthetic-staff-token"}


def _moderation_identity(is_staff=False, is_superuser=False, is_active=True):
    return {
        "data": {
            "me": {
                "id": "moderator-1",
                "email": "moderator@example.test",
                "isActive": is_active,
                "isStaff": is_staff,
                "isSuperuser": is_superuser,
            }
        }
    }


def _moderation_queue_payload():
    return {
        "data": {
            "adminReviews": {
                "items": [{
                    "id": "501",
                    "gameBggId": 13,
                    "gameName": "Catan",
                    "rating": 5,
                    "body": "Great game",
                    "createdAt": "2026-11-05T16:30:00Z",
                    "status": "PENDING",
                }],
                "page": 2,
                "pageSize": 17,
                "total": 18,
                "totalPages": 2,
            }
        }
    }


def _moderation_action_payload(
    status="ACCEPTED",
    deleted=False,
    publicly_visible=True,
):
    return {
        "data": {
            "moderateReview": {
                "success": True,
                "review": {
                    "id": "501",
                    "status": status,
                    "deleted": deleted,
                    "publiclyVisible": publicly_visible,
                },
                "userErrors": [],
            }
        }
    }


def _action_calls(upstream):
    return [
        call for call in upstream.call_args_list
        if "moderateReview" in call.args[0]
    ]


def test_admin_review_routes_and_services_are_registered():
    adapter = app.url_map.bind("localhost")
    queue_endpoint, _ = adapter.match(MODERATION_QUEUE, method="GET")
    action_endpoint, _ = adapter.match(MODERATION_ACTION, method="POST")

    assert queue_endpoint
    assert action_endpoint
    assert callable(getattr(services, "admin_list_reviews", None))
    assert callable(getattr(services, "admin_moderate_review", None))


def test_admin_review_contract_matches_canonical_openapi():
    path = Path(__file__).resolve().parents[1] / "specs" / "openapi.yaml"
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    queue = contract["paths"][MODERATION_QUEUE]["get"]
    action = contract["paths"][f"{MODERATION_QUEUE}/{{review_id}}/actions"]["post"]

    assert queue["operationId"] == "adminListReviews"
    assert queue["security"] == [{"BearerAuth": []}]
    assert queue["responses"]["200"]["headers"]["Cache-Control"]["$ref"] == (
        "#/components/headers/AdminNoStore"
    )
    assert action["operationId"] == "adminModerateReview"
    assert action["security"] == [{"BearerAuth": []}]
    assert action["requestBody"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ModerateReviewRequest"
    )
    assert action["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ModerateReviewResponse"
    )
    assert contract["components"]["schemas"]["ReviewModerationAction"]["enum"] == [
        "ACCEPT", "REJECT", "DELETE",
    ]
    assert "cache_refresh_pending" in contract["components"]["schemas"][
        "ModerateReviewResponse"
    ]["required"]


def test_admin_review_queue_maps_core_fields_and_pagination():
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            _moderation_queue_payload(),
        ],
    ) as upstream:
        response = app.test_client().get(
            f"{MODERATION_QUEUE}?status=PENDING&page=2&page_size=17",
            headers=MODERATION_AUTH,
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "items": [{
            "review_id": 501,
            "game_bgg_id": 13,
            "game_name": "Catan",
            "rating": 5,
            "body": "Great game",
            "created_at": "2026-11-05T16:30:00Z",
            "status": "PENDING",
        }],
        "page": 2,
        "page_size": 17,
        "total": 18,
        "total_pages": 2,
    }
    queue_call = next(call for call in upstream.call_args_list if "adminReviews" in call.args[0])
    assert queue_call.args[1] == {"status": "PENDING", "page": 2, "pageSize": 17}
    assert queue_call.args[2] == MODERATION_AUTH["Authorization"]


def test_admin_review_accept_maps_action_and_core_response():
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_superuser=True),
            _moderation_action_payload(),
        ],
    ) as upstream, patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": "ACCEPT"},
            headers=MODERATION_AUTH,
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "review_id": 501,
        "status": "ACCEPTED",
        "deleted": False,
        "publicly_visible": True,
        "cache_refresh_pending": False,
    }
    mutation = _action_calls(upstream)
    assert len(mutation) == 1
    assert mutation[0].args[1] == {"reviewId": "501", "action": "ACCEPT"}
    invalidate.assert_called_once()


def test_admin_review_reject_maps_action_and_core_response():
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            _moderation_action_payload(
                status="REJECTED",
                publicly_visible=False,
            ),
        ],
    ) as upstream, patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": "REJECT"},
            headers=MODERATION_AUTH,
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "review_id": 501,
        "status": "REJECTED",
        "deleted": False,
        "publicly_visible": False,
        "cache_refresh_pending": False,
    }
    mutation = _action_calls(upstream)
    assert len(mutation) == 1
    assert mutation[0].args[1] == {"reviewId": "501", "action": "REJECT"}
    invalidate.assert_called_once_with(501)


def test_admin_review_restore_maps_accept_for_a_rejected_review():
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_superuser=True),
            _moderation_action_payload(
                status="ACCEPTED",
                publicly_visible=True,
            ),
        ],
    ) as upstream, patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": "ACCEPT"},
            headers=MODERATION_AUTH,
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "review_id": 501,
        "status": "ACCEPTED",
        "deleted": False,
        "publicly_visible": True,
        "cache_refresh_pending": False,
    }
    mutation = _action_calls(upstream)
    assert len(mutation) == 1
    assert mutation[0].args[1] == {"reviewId": "501", "action": "ACCEPT"}
    invalidate.assert_called_once_with(501)


def test_admin_review_same_state_action_returns_idempotent_success():
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            _moderation_action_payload(
                status="REJECTED",
                publicly_visible=False,
            ),
        ],
    ) as upstream, patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": "REJECT"},
            headers=MODERATION_AUTH,
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "review_id": 501,
        "status": "REJECTED",
        "deleted": False,
        "publicly_visible": False,
        "cache_refresh_pending": False,
    }
    mutation = _action_calls(upstream)
    assert len(mutation) == 1
    assert mutation[0].args[1] == {"reviewId": "501", "action": "REJECT"}
    invalidate.assert_called_once_with(501)


@pytest.mark.parametrize(
    "identity",
    [
        _moderation_identity(is_staff=True),
        _moderation_identity(is_superuser=True),
    ],
)
def test_admin_review_queue_accepts_authenticated_staff_or_superuser(identity):
    with patch(
        "src.proxy._graphql_request",
        side_effect=[identity, _moderation_queue_payload()],
    ) as upstream:
        response = app.test_client().get(MODERATION_QUEUE, headers=MODERATION_AUTH)

    assert response.status_code == 200
    assert upstream.call_args_list[0].args[2] == MODERATION_AUTH["Authorization"]


def test_admin_review_queue_rejects_missing_authorization():
    with patch("src.proxy._graphql_request") as upstream:
        response = app.test_client().get(MODERATION_QUEUE)

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    upstream.assert_not_called()


def test_admin_review_queue_rejects_authorized_context_without_user():
    with patch("src.proxy._graphql_request", return_value={"data": {"me": None}}) as upstream:
        response = app.test_client().get(MODERATION_QUEUE, headers=MODERATION_AUTH)

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert upstream.call_count == 1


def test_admin_review_queue_rejects_authenticated_non_staff_user():
    with patch(
        "src.proxy._graphql_request",
        return_value=_moderation_identity(),
    ) as upstream:
        response = app.test_client().get(MODERATION_QUEUE, headers=MODERATION_AUTH)

    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    assert upstream.call_count == 1


def test_admin_review_queue_rejects_inactive_staff_user():
    with patch(
        "src.proxy._graphql_request",
        return_value=_moderation_identity(is_staff=True, is_active=False),
    ) as upstream:
        response = app.test_client().get(MODERATION_QUEUE, headers=MODERATION_AUTH)

    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    assert upstream.call_count == 1


def test_admin_review_action_rejects_operation_key_without_user(monkeypatch):
    monkeypatch.setattr(
        "src.opkey_middleware.validate_op_key_with_core",
        lambda raw_key, path, method: {"valid": True},
    )
    with patch("src.proxy._graphql_request") as upstream:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": "ACCEPT"},
            headers={"X-Op-Key": "synthetic-valid-op-key"},
        )

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    upstream.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        f"{MODERATION_QUEUE}?status=APPROVED",
        f"{MODERATION_QUEUE}?page=0",
        f"{MODERATION_QUEUE}?page_size=101",
    ],
)
def test_admin_review_queue_validates_filters_without_core_call(path):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request") as upstream:
        response = app.test_client().get(path, headers=MODERATION_AUTH)

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["errors"][0]["code"] == "INVALID"
    upstream.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"action": "APPROVE"},
        {"action": "ACCEPT", "reason": "not in the canonical request schema"},
    ],
)
def test_admin_review_action_validates_request_without_core_mutation(payload):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request") as upstream:
        response = app.test_client().post(
            MODERATION_ACTION,
            json=payload,
            headers=MODERATION_AUTH,
        )

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    upstream.assert_not_called()


def test_admin_review_upstream_error_is_sanitized():
    private_details = (
        "RuntimeError: failed at http://core.internal/graphql "
        "Authorization: Bearer synthetic-core-credential"
    )
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            UpstreamError(private_details),
        ],
    ):
        response = app.test_client().get(MODERATION_QUEUE, headers=MODERATION_AUTH)

    body = response.get_data(as_text=True)
    assert response.status_code == 502
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"error": "upstream GraphQL request failed"}
    for private_value in (
        "RuntimeError",
        "Traceback",
        "http://core.internal/graphql",
        "Authorization",
        "Bearer",
        private_details,
    ):
        assert private_value not in body


def test_admin_review_unexpected_upstream_exception_is_sanitized():
    private_details = (
        "RuntimeError: failed at http://core.internal/graphql "
        "Authorization: bearer-secret"
    )
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            RuntimeError(private_details),
        ],
    ):
        response = app.test_client().get(MODERATION_QUEUE, headers=MODERATION_AUTH)

    body = response.get_data(as_text=True)
    assert response.status_code == 502
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"error": "upstream GraphQL request failed"}
    for private_value in (
        "RuntimeError",
        "Traceback",
        "http://core.internal/graphql",
        "Authorization",
        "bearer-secret",
        private_details,
    ):
        assert private_value not in body


@pytest.mark.parametrize(
    ("core_error", "status", "message"),
    [
        ("REVIEW_NOT_FOUND", 404, "Review not found."),
        (
            "INVALID_TRANSITION",
            409,
            "Review action is not valid for the current state.",
        ),
    ],
)
def test_admin_review_action_maps_explicit_core_errors_without_leaking_details(
    core_error,
    status,
    message,
):
    private_details = (
        f"internal moderation diagnostic at http://core.internal/{core_error} "
        "with synthetic-token-value"
    )
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            {
                "errors": [{
                    "message": private_details,
                    "extensions": {"code": core_error},
                }],
            },
        ],
    ) as upstream, patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": "ACCEPT"},
            headers=MODERATION_AUTH,
        )

    body = response.get_data(as_text=True)
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"error": message}
    for private_value in (
        "internal moderation diagnostic",
        "http://core.internal",
        "synthetic-token-value",
        private_details,
    ):
        assert private_value not in body
    assert len(_action_calls(upstream)) == 1
    invalidate.assert_not_called()


@pytest.mark.parametrize("core_error", ["INTERNAL_SERVER_ERROR", "CONFLICT"])
def test_admin_review_action_maps_non_transition_core_errors_to_sanitized_502(
    core_error,
):
    private_details = "private Core diagnostic at http://core.internal/action"
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            {
                "errors": [{
                    "message": private_details,
                    "extensions": {"code": core_error},
                }],
            },
        ],
    ) as upstream, patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": "ACCEPT"},
            headers=MODERATION_AUTH,
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 502
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"error": "upstream GraphQL request failed"}
    assert private_details not in body
    assert "http://core.internal" not in body
    assert len(_action_calls(upstream)) == 1
    invalidate.assert_not_called()


@pytest.mark.parametrize(
    ("scenario", "action"),
    [
        ("unknown review ID", "DELETE"),
        ("non-delete action on a soft-deleted review", "ACCEPT"),
    ],
)
def test_admin_review_action_maps_review_not_found_scenarios_to_sanitized_404(
    scenario,
    action,
):
    private_details = (
        f"private Core detail for {scenario} at "
        "http://core.internal/review/501 with synthetic-token-value"
    )
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            {
                "errors": [{
                    "message": private_details,
                    "extensions": {"code": "REVIEW_NOT_FOUND"},
                }],
            },
        ],
    ) as upstream, patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": action},
            headers=MODERATION_AUTH,
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"error": "Review not found."}
    for private_value in (
        "private Core detail",
        "http://core.internal",
        "synthetic-token-value",
        private_details,
    ):
        assert private_value not in body
    assert len(_action_calls(upstream)) == 1
    invalidate.assert_not_called()


def test_admin_review_repeated_delete_returns_idempotent_success():
    delete_result = _moderation_action_payload(
        status="ACCEPTED",
        deleted=True,
        publicly_visible=False,
    )
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            delete_result,
            _moderation_identity(is_staff=True),
            delete_result,
        ],
    ) as upstream, patch(
        "src.catalog_cache.invalidate_catalog_cache",
    ) as invalidate:
        client = app.test_client()
        responses = [
            client.post(
                MODERATION_ACTION,
                json={"action": "DELETE"},
                headers=MODERATION_AUTH,
            )
            for _ in range(2)
        ]

    expected = {
        "review_id": 501,
        "status": "ACCEPTED",
        "deleted": True,
        "publicly_visible": False,
        "cache_refresh_pending": False,
    }
    assert [response.status_code for response in responses] == [200, 200]
    assert [response.get_json() for response in responses] == [expected, expected]
    assert len(_action_calls(upstream)) == 2
    assert all(
        call.args[1] == {"reviewId": "501", "action": "DELETE"}
        for call in _action_calls(upstream)
    )
    assert invalidate.call_count == 2


@pytest.mark.parametrize(
    ("action", "status", "deleted", "publicly_visible"),
    [
        ("ACCEPT", "ACCEPTED", False, True),
        ("REJECT", "REJECTED", False, False),
        ("DELETE", "ACCEPTED", True, False),
    ],
)
def test_admin_review_retry_success_keeps_single_core_mutation_and_clears_pending(
    action,
    status,
    deleted,
    publicly_visible,
):
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            _moderation_action_payload(
                status=status,
                deleted=deleted,
                publicly_visible=publicly_visible,
            ),
        ],
    ) as upstream, patch(
        "src.catalog_cache.invalidate_catalog_cache",
        side_effect=[RuntimeError("synthetic cache outage"), None],
    ) as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": action},
            headers=MODERATION_AUTH,
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "review_id": 501,
        "status": status,
        "deleted": deleted,
        "publicly_visible": publicly_visible,
        "cache_refresh_pending": False,
    }
    assert invalidate.call_count == 2
    assert len(_action_calls(upstream)) == 1


@pytest.mark.parametrize(
    ("action", "status", "deleted", "publicly_visible"),
    [
        ("ACCEPT", "ACCEPTED", False, True),
        ("REJECT", "REJECTED", False, False),
        ("DELETE", "ACCEPTED", True, False),
    ],
)
def test_admin_review_retry_exhaustion_preserves_committed_success_as_pending(
    action,
    status,
    deleted,
    publicly_visible,
):
    with patch(
        "src.proxy._graphql_request",
        side_effect=[
            _moderation_identity(is_staff=True),
            _moderation_action_payload(
                status=status,
                deleted=deleted,
                publicly_visible=publicly_visible,
            ),
        ],
    ) as upstream, patch(
        "src.catalog_cache.invalidate_catalog_cache",
        side_effect=[
            RuntimeError("synthetic cache outage"),
            RuntimeError("synthetic cache outage"),
        ],
    ) as invalidate:
        response = app.test_client().post(
            MODERATION_ACTION,
            json={"action": action},
            headers=MODERATION_AUTH,
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "review_id": 501,
        "status": status,
        "deleted": deleted,
        "publicly_visible": publicly_visible,
        "cache_refresh_pending": True,
    }
    assert "synthetic cache outage" not in body
    assert invalidate.call_count == 2
    assert len(_action_calls(upstream)) == 1


def test_review_forwards_valid_data_and_returns_pending_response():
    result = {"created": True, "status": "PENDING", "created_at": "2026-01-02T03:04:05Z"}
    with patch("app.create_review", return_value=result) as create_review:
        response = app.test_client().post(
            "/api/v1/games/watergate/reviews",
            json={"rating": 4, "body": "  Great game  "},
            headers={"Authorization": "Bearer synthetic-token"},
        )

    assert response.status_code == 201
    assert response.get_json() == result
    create_review.assert_called_once_with("watergate", 4, "Great game", "Bearer synthetic-token")


@pytest.mark.parametrize("payload", [
    {"rating": 0, "body": "Text"},
    {"rating": 6, "body": "Text"},
    {"rating": True, "body": "Text"},
    {"rating": 4, "body": "   "},
    {"rating": 4, "body": "a" * 2001},
])
def test_review_rejects_invalid_input_without_calling_core(payload):
    with patch("app.create_review") as create_review:
        response = app.test_client().post(
            "/api/v1/games/watergate/reviews", json=payload,
            headers={"Authorization": "Bearer synthetic-token"},
        )

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "INVALID"
    create_review.assert_not_called()


def test_review_requires_authentication_without_calling_core():
    with patch("app.create_review") as create_review:
        response = app.test_client().post(
            "/api/v1/games/watergate/reviews", json={"rating": 4, "body": "Text"},
        )

    assert response.status_code == 401
    assert response.get_json()["errors"][0]["code"] == "UNAUTHENTICATED"
    create_review.assert_not_called()


def test_review_opkey_alone_does_not_authorize_submission():
    with patch("app.create_review") as create_review:
        response = app.test_client().post(
            "/api/v1/games/watergate/reviews", json={"rating": 4, "body": "Text"},
            headers={"X-Op-Key": "synthetic-op-key"},
        )

    assert response.status_code == 401
    create_review.assert_not_called()


@pytest.mark.parametrize("code,status", [
    ("UNAUTHENTICATED", 401),
    ("PRODUCT_NOT_FOUND", 404),
    ("REVIEW_ALREADY_EXISTS", 409),
    ("RATING_OUT_OF_RANGE", 400),
    ("BODY_REQUIRED", 400),
    ("BODY_TOO_LONG", 400),
])
def test_review_known_errors_do_not_expose_upstream_messages(code, status):
    with patch("app.create_review", side_effect=UpstreamError("private upstream detail", code)):
        response = app.test_client().post(
            "/api/v1/games/watergate/reviews", json={"rating": 4, "body": "Text"},
            headers={"Authorization": "Bearer synthetic-token"},
        )

    assert response.status_code == status
    assert response.get_json()["errors"][0]["code"] == code
    assert "private upstream detail" not in response.get_data(as_text=True)


def test_review_error_responses_match_openapi_error_shape():
    path = Path(__file__).resolve().parents[1] / "specs" / "openapi.yaml"
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    operation = contract["paths"]["/api/v1/games/{slug}/reviews"]["post"]
    assert operation["security"] == [{"BearerAuth": []}]
    responses = operation["responses"]
    for status in ("400", "401", "404", "409", "502"):
        assert responses[status]["content"]["application/json"]["schema"]["$ref"] == (
            "#/components/schemas/ReviewErrorResponse"
        )
    schema = contract["components"]["schemas"]["ReviewErrorResponse"]
    assert "errors" in schema["required"]
    assert schema["properties"]["errors"]["items"]["$ref"] == "#/components/schemas/ReviewError"
    assert "code" in contract["components"]["schemas"]["ReviewError"]["required"]


def test_review_returns_structured_error_for_upstream_failure():
    with patch(
        "app.create_review",
        side_effect=UpstreamError("internal GraphQL details", "UPSTREAM_ERROR"),
    ):
        response = app.test_client().post(
            "/api/v1/games/test-game/reviews",
            json={"rating": 5, "body": "Good game"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 502
    assert response.get_json() == {
        "errors": [{
            "code": "UPSTREAM_ERROR",
            "message": "upstream GraphQL request failed",
        }],
    }
    assert "internal GraphQL details" not in response.get_data(as_text=True)
