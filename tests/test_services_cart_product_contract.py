from unittest.mock import patch

import src.services as services


def _resp(data):
    return type("R", (), {"json": lambda self: {"data": data}, "raise_for_status": lambda self: None})()


def test_get_product_detail_sends_slug_and_maps():
    def fake_post(url, json=None, timeout=None, headers=None):
        body = json or {}
        assert "productBySlug" in body.get("query", "")
        vars = body.get("variables") or {}
        assert vars.get("slug") == "game-slug"
        return _resp({"productBySlug": {"bggId": 42, "name": "G", "releaseYear": 2021, "minPlayers": 1, "maxPlayers": 4, "playingTimeMinutes": 60, "minAge": 10, "weight": 1.2, "category": "Family", "price": 30.0, "quantity": 5, "publisher": "P", "imageUrl": "u", "reviewSummary": {"approvedReviewCount": 1, "averageRating": 4.5}, "approvedReviews": []}})

    with patch("src.proxy.requests.post", side_effect=fake_post):
        res = services.get_product_detail("game-slug")
        assert res["bgg_id"] == 42


def test_cart_add_update_remove_and_get_shapes_and_user_errors():
    # addToCart
    def fake_post_add(url, json=None, timeout=None, headers=None):
        body = json or {}
        assert "addToCart" in body.get("query", "")
        vars = body.get("variables") or {}
        assert vars.get("bggId") == 10
        assert vars.get("quantity") == 3
        return _resp({"addToCart": {"cart": {"cartId": "c1", "subtotal": 120, "lines": []}, "userErrors": []}})

    with patch("src.proxy.requests.post", side_effect=fake_post_add):
        res = services.add_to_cart(10, 3, cart_id="c1")
        assert res["cart_id"] == "c1"

    # updateCartQuantity
    def fake_post_update(url, json=None, timeout=None, headers=None):
        body = json or {}
        assert "updateCartQuantity" in body.get("query", "")
        vars = body.get("variables") or {}
        assert vars.get("bggId") == 10
        assert vars.get("quantity") == 5
        return _resp({"updateCartQuantity": {"cart": {"cartId": "c1", "subtotal": 200, "lines": []}, "userErrors": []}})

    with patch("src.proxy.requests.post", side_effect=fake_post_update):
        res = services.update_cart_quantity(10, 5, cart_id="c1")
        assert res["total"] == 200

    # removeFromCart
    def fake_post_remove(url, json=None, timeout=None, headers=None):
        body = json or {}
        assert "removeFromCart" in body.get("query", "")
        vars = body.get("variables") or {}
        assert vars.get("bggId") == 10
        return _resp({"removeFromCart": {"cart": {"cartId": "c1", "subtotal": 0, "lines": []}, "userErrors": []}})

    with patch("src.proxy.requests.post", side_effect=fake_post_remove):
        res = services.remove_from_cart(10, cart_id="c1")
        assert res["total"] == 0

    # simulate userErrors on addToCart -> warnings present
    def fake_post_add_errors(url, json=None, timeout=None, headers=None):
        return _resp({"addToCart": {"cart": {"cartId": "c1", "subtotal": 100, "lines": []}, "userErrors": [{"field": "quantity", "code": "OUT_OF_STOCK", "message": "Not enough stock"}]}})

    with patch("src.proxy.requests.post", side_effect=fake_post_add_errors):
        res = services.add_to_cart(10, 1000, cart_id="c1")
        assert "warnings" in res and isinstance(res["warnings"], list)
