from flask import jsonify, request

from ..dtos.wishlist import GRAPHQL_INT_MAX, WishlistAddRequestDto
from ..proxy import UpstreamError


def _unauthorized():
    return jsonify({
        "errors": [{"code": "UNAUTHENTICATED", "message": "Authentication is required."}]
    }), 401


def _authorized_token():
    return request.headers.get("Authorization")


def _error_response(exc):
    if exc.code == "UNAUTHENTICATED":
        return _unauthorized()
    if exc.code == "PRODUCT_NOT_FOUND":
        return jsonify({
            "errors": [{"code": "PRODUCT_NOT_FOUND", "message": "The requested game does not exist."}]
        }), 404
    return jsonify({"error": "upstream GraphQL request failed"}), 502


def _call(service, *args):
    try:
        return service(*args)
    except UpstreamError as exc:
        return _error_response(exc)


def _path_bgg_id(value):
    try:
        bgg_id = int(value)
    except (TypeError, ValueError):
        raise ValueError("bgg_id must be a positive integer")
    if str(bgg_id) != value or not 1 <= bgg_id <= GRAPHQL_INT_MAX:
        raise ValueError("bgg_id must be a positive integer")
    return bgg_id


def list_wishlist(service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    result = _call(service, token)
    if isinstance(result, tuple):
        return result
    return jsonify({"items": result}), 200


def add_wishlist_item(service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    try:
        item = WishlistAddRequestDto.from_payload(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result = _call(service, item.bgg_id, token)
    if isinstance(result, tuple):
        return result
    return jsonify(result), 200


def remove_wishlist_item(bgg_id, service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    try:
        bgg_id = _path_bgg_id(bgg_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result = _call(service, bgg_id, token)
    if isinstance(result, tuple):
        return result
    return jsonify(result), 200
