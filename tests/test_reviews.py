from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app import app
from src.proxy import UpstreamError


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
