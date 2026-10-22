from unittest.mock import MagicMock, patch

import pytest
import requests

from app import app
from src.proxy import UpstreamError, add_to_wishlist, get_wishlist, remove_from_wishlist


PRODUCT = {
    "bgg_id": 7,
    "name": "Game",
    "release_year": 2024,
    "min_players": 1,
    "max_players": 4,
    "playing_time_minutes": 60,
    "min_age": 10,
    "weight": 2.5,
    "category": ["Strategy"],
    "price": 25.0,
    "quantity": 5,
    "publisher": "Publisher",
    "image_url": "/media/game.webp",
}

CORE_PRODUCT = {
    "bggId": 7,
    "name": "Game",
    "releaseYear": 2024,
    "minPlayers": 1,
    "maxPlayers": 4,
    "playingTimeMinutes": 60,
    "minAge": 10,
    "weight": 2.5,
    "category": ["Strategy"],
    "price": 25.0,
    "quantity": 5,
    "publisher": "Publisher",
    "imageUrl": "/media/game.webp",
}


def test_wishlist_routes_require_authorization():
    client = app.test_client()
    responses = [
        client.get("/api/v1/wishlist"),
        client.post("/api/v1/wishlist", json={"bgg_id": 7}),
        client.delete("/api/v1/wishlist/7"),
    ]
    assert [response.status_code for response in responses] == [401, 401, 401]
    assert all(
        response.get_json()["errors"][0]["code"] == "UNAUTHENTICATED"
        for response in responses
    )


def test_list_wishlist_forwards_exact_bearer_token_and_maps_products():
    with patch("app.get_wishlist", return_value=[PRODUCT]) as service:
        response = app.test_client().get(
            "/api/v1/wishlist",
            headers={"Authorization": "Bearer caller-token"},
        )

    assert response.status_code == 200
    assert response.get_json() == {"items": [PRODUCT]}
    service.assert_called_once_with("Bearer caller-token")


def test_add_wishlist_validates_positive_bgg_id_and_returns_product():
    client = app.test_client()
    with patch("app.add_to_wishlist", return_value=PRODUCT) as service:
        response = client.post(
            "/api/v1/wishlist",
            json={"bgg_id": 7},
            headers={"Authorization": "Bearer caller-token"},
        )

    assert response.status_code == 200
    assert response.get_json() == PRODUCT
    service.assert_called_once_with(7, "Bearer caller-token")

    for payload in (None, {}, {"bgg_id": 0}, {"bgg_id": -1}, {"bgg_id": True},
                    {"bgg_id": 2**31}, {"bgg_id": "7"}, {"bgg_id": 7, "user_id": 8}):
        invalid = client.post(
            "/api/v1/wishlist",
            json=payload,
            headers={"Authorization": "Bearer caller-token"},
        )
        assert invalid.status_code == 400
    service.assert_called_once()


def test_remove_wishlist_validates_path_id_and_returns_product():
    client = app.test_client()
    with patch("app.remove_from_wishlist", return_value=PRODUCT) as service:
        response = client.delete(
            "/api/v1/wishlist/7",
            headers={"Authorization": "Bearer caller-token"},
        )
    assert response.status_code == 200
    assert response.get_json() == PRODUCT
    service.assert_called_once_with(7, "Bearer caller-token")

    for invalid_id in ("0", "-1", "01", "1.5", "not-an-id", str(2**31)):
        invalid = client.delete(
            f"/api/v1/wishlist/{invalid_id}",
            headers={"Authorization": "Bearer caller-token"},
        )
        assert invalid.status_code == 400
    service.assert_called_once()


@pytest.mark.parametrize(
    ("operation", "method", "path", "payload"),
    [
        ("get_wishlist", "get", "/api/v1/wishlist", None),
        ("add_to_wishlist", "post", "/api/v1/wishlist", {"bgg_id": 7}),
        ("remove_from_wishlist", "delete", "/api/v1/wishlist/7", None),
    ],
)
def test_core_errors_are_mapped_without_leaking_upstream_details(
    operation, method, path, payload
):
    with patch(
        f"app.{operation}",
        side_effect=UpstreamError(
            "GraphQL error at https://internal.example/graphql with stack trace"
        ),
    ):
        response = getattr(app.test_client(), method)(
            path, json=payload, headers={"Authorization": "Bearer caller-token"}
        )

    assert response.status_code == 502
    body = response.get_data(as_text=True)
    assert body == '{"error":"upstream GraphQL request failed"}\n'
    assert "internal.example" not in body
    assert "stack trace" not in body
    assert "caller-token" not in body


def test_invalid_core_bearer_maps_to_unauthorized():
    with patch(
        "app.get_wishlist",
        side_effect=UpstreamError("Authentication is required.", "UNAUTHENTICATED"),
    ):
        response = app.test_client().get(
            "/api/v1/wishlist", headers={"Authorization": "Bearer invalid"}
        )
    assert response.status_code == 401
    assert response.get_json() == {
        "errors": [{"code": "UNAUTHENTICATED", "message": "Authentication is required."}]
    }


def test_graphql_auth_error_maps_to_unauthorized():
    upstream = MagicMock()
    upstream.json.return_value = {
        "errors": [{
            "message": "Authentication is required.",
        }]
    }
    with patch("src.proxy.requests.post", return_value=upstream):
        response = app.test_client().get(
            "/api/v1/wishlist", headers={"Authorization": "Bearer invalid"}
        )
    assert response.status_code == 401
    assert response.get_json()["errors"][0]["code"] == "UNAUTHENTICATED"
    assert "Sensitive" not in response.get_data(as_text=True)


def test_graphql_missing_product_error_is_sanitized_as_not_found():
    upstream = MagicMock()
    upstream.json.return_value = {
        "errors": [{
            "message": "Product not found.",
        }]
    }
    with patch("src.proxy.requests.post", return_value=upstream):
        response = app.test_client().post(
            "/api/v1/wishlist",
            json={"bgg_id": 999},
            headers={"Authorization": "Bearer caller-token"},
        )
    assert response.status_code == 404
    assert response.get_json() == {
        "errors": [{"code": "PRODUCT_NOT_FOUND", "message": "The requested game does not exist."}]
    }
    assert "Sensitive" not in response.get_data(as_text=True)


def test_transport_failure_returns_sanitized_upstream_error():
    with patch(
        "src.proxy.requests.post",
        side_effect=requests.Timeout("https://internal.example/graphql timed out"),
    ):
        response = app.test_client().get(
            "/api/v1/wishlist", headers={"Authorization": "Bearer caller-token"}
        )
    assert response.status_code == 502
    body = response.get_data(as_text=True)
    assert "upstream GraphQL request failed" in body
    assert "internal.example" not in body
    assert "caller-token" not in body


def test_wishlist_proxy_maps_graphql_products_and_forwards_token():
    response = MagicMock()
    response.json.return_value = {"data": {"myWishlist": [CORE_PRODUCT]}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        products = get_wishlist("Bearer caller-token")

    assert products == [PRODUCT]
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer caller-token"}
    assert post.call_args.kwargs["json"]["variables"] == {}
    assert "myWishlist" in post.call_args.kwargs["json"]["query"]
    assert "bggId name releaseYear minPlayers maxPlayers" in post.call_args.kwargs["json"]["query"]


@pytest.mark.parametrize(
    ("operation", "field"),
    [("add_to_wishlist", "addToWishlist"), ("remove_from_wishlist", "removeFromWishlist")],
)
def test_wishlist_mutation_proxy_uses_core_contract(operation, field):
    response = MagicMock()
    response.json.return_value = {"data": {field: CORE_PRODUCT}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        product = globals()[operation](7, "Bearer caller-token")

    assert product == PRODUCT
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer caller-token"}
    assert post.call_args.kwargs["json"]["variables"] == {"bggId": 7}
    assert field in post.call_args.kwargs["json"]["query"]
