from flask import current_app, jsonify, request

from ..dtos.cart import GRAPHQL_INT_MAX, CartItemRequestDto, CartResponseDto
from ..proxy import UpstreamError


def _identity():
    token = request.headers.get("Authorization")
    cart_id = None if token else request.cookies.get(current_app.config["CART_COOKIE_NAME"])
    return cart_id, token


def _respond(result, token):
    response_data = CartResponseDto.from_dict(result).to_dict()
    warnings = response_data["warnings"]
    status = 200
    if warnings:
        status = 400
        codes = [warning["code"] for warning in warnings]
        if "INSUFFICIENT_STOCK" in codes:
            status = 409
        elif "PRODUCT_NOT_FOUND" in codes:
            status = 404
    response = jsonify(response_data)
    cart_id = result.get("cart_id")
    if not token and cart_id:
        response.set_cookie(
            current_app.config["CART_COOKIE_NAME"],
            cart_id,
            httponly=True,
            secure=current_app.config["CART_COOKIE_SECURE"],
            samesite="Lax",
            path="/",
        )
    return response, status


def _execute(operation, *args):
    cart_id, token = _identity()
    try:
        return _respond(operation(*args, cart_id, token), token)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502


def read_cart(service):
    return _execute(service)


def add_cart_item(service):
    try:
        item = CartItemRequestDto.from_payload(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return _execute(service, item.bgg_id, item.quantity)


def _path_bgg_id(value):
    try:
        bgg_id = int(value)
    except (TypeError, ValueError):
        raise ValueError("bgg_id must be a positive integer")
    if str(bgg_id) != value or not 1 <= bgg_id <= GRAPHQL_INT_MAX:
        raise ValueError("bgg_id must be a positive integer")
    return bgg_id


def update_cart_item(bgg_id, service):
    try:
        bgg_id = _path_bgg_id(bgg_id)
        item = CartItemRequestDto.from_payload(
            request.get_json(silent=True), include_bgg_id=False
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return _execute(service, bgg_id, item.quantity)


def remove_cart_item(bgg_id, service):
    try:
        bgg_id = _path_bgg_id(bgg_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return _execute(service, bgg_id)
