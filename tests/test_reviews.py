from unittest.mock import patch

from app import app
from src.proxy import UpstreamError


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
