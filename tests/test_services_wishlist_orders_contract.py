from unittest.mock import patch

import src.services as services
from src.proxy import UpstreamError


def _resp(data):
    return type("R", (), {"json": lambda self: {"data": data}, "raise_for_status": lambda self: None})()


def test_get_wishlist_and_add_remove_shape():
    def fake_post_get(url, json=None, timeout=None, headers=None):
        body = json or {}
        assert "myWishlist" in body.get("query", "")
        return _resp({"myWishlist": [{"bggId": 7, "name": "WGame", "releaseYear": 2019, "minPlayers": 1, "maxPlayers": 6, "playingTimeMinutes": 30, "minAge": 8, "weight": 1.0, "category": "Family", "price": 25.0, "quantity": 2, "publisher": "P", "imageUrl": "u"}]})

    with patch("src.proxy.requests.post", side_effect=fake_post_get):
        res = services.get_wishlist(token="T")
        assert isinstance(res, list)
        assert res[0]["bgg_id"] == 7

    def fake_post_add(url, json=None, timeout=None, headers=None):
        body = json or {}
        assert "addToWishlist" in body.get("query", "")
        vars = body.get("variables") or {}
        assert vars.get("bggId") == 99
        return _resp({"addToWishlist": {"bggId": 99, "name": "New", "releaseYear": 2022, "minPlayers": 1, "maxPlayers": 4, "playingTimeMinutes": 45, "minAge": 12, "weight": 1.5, "category": "Strategy", "price": 40.0, "quantity": 3, "publisher": "P", "imageUrl": "u"}})

    with patch("src.proxy.requests.post", side_effect=fake_post_add):
        p = services.add_to_wishlist(99, token="T")
        assert p["bgg_id"] == 99

    def fake_post_remove(url, json=None, timeout=None, headers=None):
        body = json or {}
        assert "removeFromWishlist" in body.get("query", "")
        return _resp({"removeFromWishlist": {"bggId": 99, "name": "New", "releaseYear": 2022, "minPlayers": 1, "maxPlayers": 4, "playingTimeMinutes": 45, "minAge": 12, "weight": 1.5, "category": "Strategy", "price": 40.0, "quantity": 3, "publisher": "P", "imageUrl": "u"}})

    with patch("src.proxy.requests.post", side_effect=fake_post_remove):
        p = services.remove_from_wishlist(99, token="T")
        assert p["bgg_id"] == 99


def test_get_orders_and_order_detail_and_not_found():
    def fake_post_orders(url, json=None, timeout=None, headers=None):
        assert "myOrders" in (json or {}).get("query", "")
        return _resp({"myOrders": [{"id": "o1", "status": "CREATED", "total": 100.0, "currency": "USD", "shippingMode": "STANDARD", "createdAt": "2020-01-01", "lines": []}]})

    with patch("src.proxy.requests.post", side_effect=fake_post_orders):
        lst = services.get_orders(token="T")
        assert isinstance(lst, list) and lst[0]["id"] == "o1"

    def fake_post_order(url, json=None, timeout=None, headers=None):
        body = json or {}
        vars = body.get("variables") or {}
        assert vars.get("id") == "o-123"
        return _resp({"myOrder": {"id": "o-123", "status": "PAID", "total": 200.0, "currency": "USD", "shippingMode": "EXPRESS", "createdAt": "2021-01-01", "lines": []}})

    with patch("src.proxy.requests.post", side_effect=fake_post_order):
        o = services.get_order("o-123", token="T")
        assert o["id"] == "o-123"

    # simulate not found
    def fake_post_order_none(url, json=None, timeout=None, headers=None):
        return _resp({"myOrder": None})

    with patch("src.proxy.requests.post", side_effect=fake_post_order_none):
        try:
            services.get_order("does-not-exist", token="T")
            assert False, "Expected UpstreamError"
        except UpstreamError as exc:
            assert exc.code == "ORDER_NOT_FOUND"
