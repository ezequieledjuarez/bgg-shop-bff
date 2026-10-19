from flask import jsonify, request

from .dto import AuthRequest, ProductQuery
from .proxy import UpstreamError


def health():
    return jsonify({"status": "healthy"}), 200


def products(list_products_service):
    query = ProductQuery.from_request_args(request.args)
    try:
        return jsonify(list_products_service(**query.as_service_kwargs())), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        return jsonify({
            "error": "upstream GraphQL request failed",
            "detail": str(exc),
        }), 502


def auth_request(operation, success_status):
    try:
        auth_request_dto = AuthRequest.from_payload(
            request.get_json(silent=True)
        )
        return jsonify(operation(auth_request_dto.payload)), success_status
    except ValueError as exc:
        return jsonify({
            "errors": [{"code": "INVALID", "message": str(exc)}],
        }), 400
    except UpstreamError as exc:
        if exc.code == "INVALID_CREDENTIALS":
            return jsonify({
                "errors": [{
                    "code": exc.code,
                    "message": "Invalid email or password.",
                }],
            }), 401
        if exc.code in ("DUPLICATE_EMAIL", "EMAIL_EXISTS"):
            return jsonify({
                "errors": [{
                    "code": exc.code,
                    "field": ["email"],
                    "message": "An account with this email already exists.",
                }],
            }), 409
        return jsonify({"error": "upstream GraphQL request failed"}), 502
