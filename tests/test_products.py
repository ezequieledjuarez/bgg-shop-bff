from unittest.mock import MagicMock, patch

from app import app
from src.proxy import UpstreamError, get_product_detail, list_products


def test_products_returns_rest_contract():
    app.testing = True
    with patch("app.list_products", return_value={
        "items": [{"bgg_id": 1, "category": ["Strategy"]}],
        "page": 1, "page_size": 20, "total": 1, "total_pages": 1,
    }) as list_products:
        response = app.test_client().get("/api/v1/products?page=1&page_size=20")

    assert response.status_code == 200
    assert response.get_json()["items"][0]["category"] == ["Strategy"]
    list_products.assert_called_once_with(
        page="1", page_size="20", search=None, year_published=None,
        min_players=None, max_players=None, category_id=None,
        price_min=None, price_max=None,
    )


def test_products_allows_frontend_origin():
    with patch("app.list_products", return_value={
        "items": [], "page": 1, "page_size": 20, "total": 0, "total_pages": 0,
    }):
        response = app.test_client().get(
            "/api/v1/products", headers={"Origin": "http://localhost:3000"}
        )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"


def test_products_rejects_unconfigured_origin():
    with patch("app.list_products", return_value={
        "items": [], "page": 1, "page_size": 20, "total": 0, "total_pages": 0,
    }):
        response = app.test_client().get(
            "/api/v1/products", headers={"Origin": "http://evil.example"}
        )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_products_rejects_invalid_pagination():
    response = app.test_client().get("/api/v1/products?page=0&page_size=20")

    assert response.status_code == 400
    assert "positive integer" in response.get_json()["error"]


def test_products_returns_502_for_upstream_failure():
    with patch("app.list_products", side_effect=UpstreamError("connection refused")):
        response = app.test_client().get("/api/v1/products")

    assert response.status_code == 502
    assert response.get_json()["error"] == "upstream GraphQL request failed"


def test_products_rejects_inverted_filter_ranges():
    response = app.test_client().get(
        "/api/v1/products?min_players=4&max_players=2"
    )

    assert response.status_code == 400
    assert "min_players" in response.get_json()["error"]


def test_products_forwards_all_rest_filters():
    with patch("app.list_products", return_value={
        "items": [], "page": 1, "page_size": 20, "total": 0, "total_pages": 0,
    }) as list_products:
        response = app.test_client().get(
            "/api/v1/products?search=game&year_published=2020&min_players=2"
            "&max_players=4&category_id=1&price_min=10&price_max=20"
        )

    assert response.status_code == 200
    list_products.assert_called_once_with(
        page=1, page_size=20, search="game", year_published="2020",
        min_players="2", max_players="4", category_id="1",
        price_min="10", price_max="20",
    )


def test_products_rejects_invalid_search():
    response = app.test_client().get("/api/v1/products?search=%20")

    assert response.status_code == 400
    assert "search" in response.get_json()["error"]


def test_products_rejects_inverted_price_range():
    response = app.test_client().get("/api/v1/products?price_min=80&price_max=10")

    assert response.status_code == 400
    assert "price_min" in response.get_json()["error"]


def test_graphql_response_is_mapped_to_rest_contract():
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "products": {
                "items": [{
                    "bggId": 7, "name": "Game", "releaseYear": 2020,
                    "minPlayers": 2, "maxPlayers": 4,
                    "playingTimeMinutes": 60, "minAge": 10, "weight": 2.5,
                    "category": ["Strategy"], "price": 12.5, "quantity": 6,
                    "publisher": "Pub", "imageUrl": "/game.jpg",
                }],
                "page": 2, "pageSize": 1, "total": 3, "totalPages": 3,
            }
        }
    }
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = list_products(
            page=2,
            page_size=1,
            search="game",
            year_published=2020,
            min_players=2,
            max_players=4,
            category_id=1,
            price_min=10,
            price_max=20,
        )

    payload = post.call_args.kwargs["json"]
    assert result["items"][0]["bgg_id"] == 7
    assert result["items"][0]["quantity"] == 6
    assert result["page_size"] == 1
    assert "quantity" in payload["query"]
    assert payload["variables"]["search"] == "game"
    assert payload["variables"]["yearPublished"] == 2020
    assert payload["variables"]["minPlayers"] == 2
    assert payload["variables"]["maxPlayers"] == 4
    assert payload["variables"]["categoryId"] == 1
    assert payload["variables"]["priceMin"] == 10
    assert payload["variables"]["priceMax"] == 20


def test_product_detail_exposes_inventory_quantity():
    response = MagicMock()
    response.json.return_value = {"data": {"productBySlug": {
        "bggId": 1,
        "name": "Game", "releaseYear": 2020, "minPlayers": 2, "maxPlayers": 4,
        "playingTimeMinutes": 60, "minAge": 10, "weight": 2.5,
        "category": ["Strategy"], "price": 12.5, "quantity": 6,
        "publisher": "Pub", "imageUrl": "/game.jpg",
        "reviewSummary": {"approvedReviewCount": 0, "averageRating": None},
        "approvedReviews": [],
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = get_product_detail("game")

    assert result["bgg_id"] == 1
    assert result["quantity"] == 6
    assert "bggId" in post.call_args.kwargs["json"]["query"]
    assert "quantity" in post.call_args.kwargs["json"]["query"]


def test_product_detail_rest_response_includes_inventory_quantity():
    with patch("app.get_product_detail", return_value={
        "bgg_id": 1,
        "name": "Game", "release_year": 2020, "min_players": 2, "max_players": 4,
        "playing_time_minutes": 60, "min_age": 10, "weight": 2.5,
        "category": ["Strategy"], "price": 12.5, "quantity": 6,
        "publisher": "Pub", "image_url": "/game.jpg",
        "review_summary": {"approved_review_count": 0, "average_rating": None},
        "approved_reviews": [],
    }):
        response = app.test_client().get("/api/v1/games/game")

    assert response.status_code == 200
    assert response.get_json()["bgg_id"] == 1
    assert response.get_json()["quantity"] == 6
