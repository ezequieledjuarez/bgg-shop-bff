from unittest.mock import MagicMock, patch

import requests

from app import app


TOKEN = "Bearer synthetic-local-session"
PRIVATE_DETAIL = "synthetic-private-upstream-detail"


def _graphql_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_empty_authenticated_order_history_is_a_successful_empty_list():
    with patch(
        "src.proxy.requests.post",
        return_value=_graphql_response({"data": {"myOrders": []}}),
    ) as post:
        response = app.test_client().get(
            "/api/v1/orders",
            headers={"Authorization": TOKEN},
        )

    assert response.status_code == 200
    assert response.get_json() == {"orders": []}
    assert post.call_args.kwargs["headers"] == {"Authorization": TOKEN}


def test_invalid_order_history_authentication_stays_401():
    with patch(
        "src.proxy.requests.post",
        return_value=_graphql_response({
            "errors": [{
                "message": PRIVATE_DETAIL,
                "extensions": {"code": "UNAUTHENTICATED"},
            }],
        }),
    ):
        response = app.test_client().get(
            "/api/v1/orders",
            headers={"Authorization": TOKEN},
        )

    assert response.status_code == 401
    assert PRIVATE_DETAIL.encode() not in response.data


def test_order_history_upstream_failure_is_sanitized_not_empty_success():
    with patch(
        "src.proxy.requests.post",
        side_effect=requests.Timeout(PRIVATE_DETAIL),
    ):
        response = app.test_client().get(
            "/api/v1/orders",
            headers={"Authorization": TOKEN},
        )

    assert response.status_code == 502
    assert response.get_json() == {"error": "upstream GraphQL request failed"}
    assert PRIVATE_DETAIL.encode() not in response.data


def test_malformed_order_history_payload_is_not_converted_to_empty_success():
    with patch(
        "src.proxy.requests.post",
        return_value=_graphql_response({"data": {"myOrders": None}}),
    ):
        response = app.test_client().get(
            "/api/v1/orders",
            headers={"Authorization": TOKEN},
        )

    assert response.status_code == 502
    assert response.get_json() == {"error": "upstream GraphQL request failed"}


def test_missing_order_history_authentication_stays_401():
    response = app.test_client().get("/api/v1/orders")

    assert response.status_code == 401
    assert response.get_json()["errors"][0]["code"] == "UNAUTHENTICATED"
