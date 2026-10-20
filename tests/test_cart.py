from unittest.mock import MagicMock, patch

from app import app
from src.proxy import (
    UpstreamError, add_to_cart, authenticate_account, get_cart, remove_from_cart,
    update_cart_quantity,
)


CART = {
    "lines": [{
        "bgg_id": 7,
        "name": "Game",
        "quantity": 2,
        "available_stock": 5,
        "unit_price": 12.5,
        "subtotal": 25.0,
    }],
    "total": 25.0,
    "warnings": [],
}


def test_get_cart_sets_secure_httponly_lax_cookie_for_guest():
    app.config["CART_COOKIE_SECURE"] = True
    with patch("app.get_cart", return_value={**CART, "cart_id": "opaque-id"}) as service:
        response = app.test_client().get("/api/v1/cart")

    assert response.status_code == 200
    assert response.get_json() == CART
    cookie = response.headers["Set-Cookie"]
    assert "cart_id=opaque-id" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" in cookie
    service.assert_called_once_with(None, None)


def test_cart_forwards_bearer_header_and_ignores_guest_cart_cookie():
    client = app.test_client()
    client.set_cookie("cart_id", "guest-id")
    with patch("app.get_cart", return_value={**CART, "cart_id": "account-id"}) as service:
        response = client.get("/api/v1/cart", headers={"Authorization": "Bearer access-token"})

    assert response.status_code == 200
    service.assert_called_once_with(None, "Bearer access-token")


def test_add_cart_item_validates_payload_and_returns_cart():
    with patch("app.add_to_cart", return_value={**CART, "cart_id": "opaque-id"}) as service:
        response = app.test_client().post(
            "/api/v1/cart/items", json={"bgg_id": 7, "quantity": 2}
        )

    assert response.status_code == 200
    assert response.get_json() == CART
    service.assert_called_once_with(7, 2, None, None)


def test_cart_mutations_reject_invalid_ids_and_quantities():
    client = app.test_client()
    assert client.post("/api/v1/cart/items", json={"bgg_id": 0, "quantity": 1}).status_code == 400
    assert client.post("/api/v1/cart/items", json={"bgg_id": 7, "quantity": True}).status_code == 400
    assert client.patch("/api/v1/cart/items/7", json={"quantity": 0}).status_code == 400
    assert client.delete("/api/v1/cart/items/not-an-id").status_code == 400
    assert client.post(
        "/api/v1/cart/items", json={"bgg_id": 7, "quantity": 1, "user_id": 4}
    ).status_code == 400


def test_patch_and_delete_cart_item_routes_forward_validated_inputs():
    client = app.test_client()
    with patch("app.update_cart_quantity", return_value={**CART, "cart_id": "guest-id"}) as update:
        response = client.patch("/api/v1/cart/items/7", json={"quantity": 3})
    assert response.status_code == 200
    update.assert_called_once_with(7, 3, None, None)

    with patch("app.remove_from_cart", return_value={**CART, "cart_id": "guest-id"}) as remove:
        response = client.delete("/api/v1/cart/items/7")
    assert response.status_code == 200
    remove.assert_called_once_with(7, "guest-id", None)


def test_stock_limit_is_returned_as_conflict_warning():
    rejected = {
        **CART,
        "cart_id": "opaque-id",
        "warnings": [{
            "code": "INSUFFICIENT_STOCK",
            "field": ["quantity"],
            "message": "Requested quantity exceeds current inventory.",
        }],
    }
    with patch("app.add_to_cart", return_value=rejected):
        response = app.test_client().post(
            "/api/v1/cart/items", json={"bgg_id": 7, "quantity": 9}
        )

    assert response.status_code == 409
    assert response.get_json()["warnings"][0]["code"] == "INSUFFICIENT_STOCK"
    assert response.get_json()["lines"] == CART["lines"]


def test_cart_proxy_maps_core_cart_fields_and_uses_cookie_identifier():
    response = MagicMock()
    response.json.return_value = {"data": {"cart": {
        "cartId": "opaque-id",
        "subtotal": 25.0,
        "lines": [{
            "bggId": 7, "name": "Game", "quantity": 2,
            "inventoryQuantity": 5, "unitPrice": 12.5, "subtotal": 25.0,
        }],
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = get_cart("opaque-id", None)

    assert result == {"cart_id": "opaque-id", **CART}
    payload = post.call_args.kwargs["json"]
    assert payload["variables"] == {"cartId": "opaque-id"}
    assert "cart(cartId: $cartId)" in payload["query"]


def test_cart_mutation_maps_stock_user_errors_and_forwards_authorization():
    response = MagicMock()
    response.json.return_value = {"data": {"addToCart": {
        "cart": {"cartId": "opaque-id", "subtotal": 25.0, "lines": []},
        "userErrors": [{
            "code": "INSUFFICIENT_STOCK",
            "field": ["quantity"],
            "message": "Requested quantity exceeds current inventory.",
        }],
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = add_to_cart(7, 9, "opaque-id", "Bearer access-token")

    assert result["warnings"][0]["code"] == "INSUFFICIENT_STOCK"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer access-token"}
    assert post.call_args.kwargs["json"]["variables"] == {
        "bggId": 7, "quantity": 9, "cartId": "opaque-id",
    }


def test_update_and_remove_proxy_use_the_core_graphql_contract():
    response = MagicMock()
    response.json.return_value = {"data": {"updateCartQuantity": {
        "cart": {"cartId": "opaque-id", "subtotal": 0, "lines": []},
        "userErrors": [],
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        update_cart_quantity(7, 3, "opaque-id", None)
    assert post.call_args.kwargs["json"]["variables"] == {
        "bggId": 7, "quantity": 3, "cartId": "opaque-id",
    }
    assert "updateCartQuantity" in post.call_args.kwargs["json"]["query"]

    response.json.return_value = {"data": {"removeFromCart": {
        "cart": {"cartId": "opaque-id", "subtotal": 0, "lines": []},
        "userErrors": [],
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        remove_from_cart(7, "opaque-id", None)
    assert post.call_args.kwargs["json"]["variables"] == {
        "bggId": 7, "cartId": "opaque-id",
    }
    query = post.call_args.kwargs["json"]["query"]
    assert "removeFromCart" in query
    assert "quantity: $quantity" not in query


def test_unknown_cart_user_errors_are_mapped_to_bad_request():
    result = {**CART, "cart_id": "opaque-id", "warnings": [{
        "code": "CORE_CART_VALIDATION", "field": None, "message": "Invalid cart operation",
    }]}
    with patch("app.add_to_cart", return_value=result):
        response = app.test_client().post(
            "/api/v1/cart/items", json={"bgg_id": 7, "quantity": 1}
        )

    assert response.status_code == 400
    assert response.get_json()["warnings"][0]["code"] == "CORE_CART_VALIDATION"


def test_cart_upstream_failure_returns_502():
    with patch("app.get_cart", side_effect=UpstreamError("details")):
        response = app.test_client().get("/api/v1/cart")

    assert response.status_code == 502
    assert response.get_json()["error"] == "upstream GraphQL request failed"


def test_login_passes_guest_cart_id_and_clears_cookie_after_success():
    client = app.test_client()
    client.set_cookie("cart_id", "guest-id")
    user = {
        "id": "1", "email": "player@example.test", "first_name": "Test",
        "last_name": "Player", "is_active": True,
    }
    session = {"access_token": "token", "refresh_token": "refresh", "csrf_token": None}
    with patch("app.authenticate_account", return_value={"user": user, "session": session}) as login:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "player@example.test", "password": "password"},
        )

    assert response.status_code == 200
    assert "cart_id=;" in response.headers["Set-Cookie"]
    assert "Max-Age=0" in response.headers["Set-Cookie"]
    login.assert_called_once_with({
        "email": "player@example.test", "password": "password", "guest_cart_id": "guest-id",
    })


def test_login_proxy_includes_guest_cart_id_in_core_input():
    response = MagicMock()
    response.json.return_value = {"data": {"login": {
        "user": {"id": "1", "email": "player@example.test", "firstName": "Test",
                 "lastName": "Player", "isActive": True},
        "tokens": {"token": "access", "refreshToken": "refresh", "csrfToken": None},
        "errors": [],
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        result = authenticate_account({
            "email": "player@example.test", "password": "password", "guest_cart_id": "guest-id",
        })

    assert result["session"]["access_token"] == "access"
    assert post.call_args.kwargs["json"]["variables"]["input"]["guestCartId"] == "guest-id"


def test_cart_item_rejects_values_above_graphql_int_max():
    client = app.test_client()
    assert client.post("/api/v1/cart/items", json={"bgg_id": 2**31, "quantity": 1}).status_code == 400
    assert client.post("/api/v1/cart/items", json={"bgg_id": 1, "quantity": 2**31}).status_code == 400
    assert client.patch("/api/v1/cart/items/2147483648", json={"quantity": 1}).status_code == 400
