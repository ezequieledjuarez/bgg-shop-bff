from unittest.mock import patch

import src.services as services
from src.proxy import UpstreamError


def _make_resp(data):
    return type("R", (), {"json": lambda self: {"data": data}, "raise_for_status": lambda self: None})()


def test_list_products_shape_and_mapping():
    def _check(body):
        assert "query" in body and "Products" in body["query"]
        vars = body.get("variables") or {}
        assert vars.get("page") == 2

    def fake_post(url, json=None, timeout=None, headers=None):
        _check(json)
        # Return a products list payload
        return _make_resp({"products": {"items": [{"bggId": 1, "name": "G1", "releaseYear": 2020, "minPlayers": 1, "maxPlayers": 4, "playingTimeMinutes": 60, "minAge": 8, "weight": 2.5, "category": "Family", "price": 20.0, "quantity": 10, "publisher": "P", "imageUrl": "u"}], "page": 2, "pageSize": 20, "total": 1, "totalPages": 1}})

    with patch("src.proxy.requests.post", side_effect=fake_post):
        res = services.list_products(page=2)
        assert res["page"] == 2
        assert len(res["items"]) == 1


def test_checkout_user_errors_raise_upstream_error():
    def fake_post(url, json=None, timeout=None, headers=None):
        # Simulate GraphQL returning a checkout with userErrors
        return _make_resp({"checkout": {"order": None, "initPoint": None, "userErrors": [{"field": "address", "code": "INVALID_ADDRESS", "message": "Address invalid"}]}})

    with patch("src.proxy.requests.post", side_effect=fake_post):
        try:
            services.checkout("standard", {"recipient": "x"}, token=None)
            assert False, "Expected UpstreamError"
        except UpstreamError as exc:
            assert exc.user_error
            assert exc.code == "INVALID_ADDRESS" or exc.code == "INVALID"
