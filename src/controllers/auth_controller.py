import logging

from flask import jsonify, request

from ..dtos import AuthRequest, AuthResponse
from ..proxy import UpstreamError


logger = logging.getLogger(__name__)


def auth_request(operation, success_status):
    try:
        payload = AuthRequest.from_payload(request.get_json(silent=True))
        result = AuthResponse.from_dict(operation(payload.payload))
        response = jsonify(result.to_dict())
        response.headers["Cache-Control"] = "no-store"
        return response, success_status
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


def current_user(operation):
    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return jsonify({
            "errors": [{
                "code": "UNAUTHENTICATED",
                "message": "Authentication is required.",
            }],
        }), 401
    try:
        result = operation(authorization)
        return jsonify(result), 200
    except UpstreamError as exc:
        if exc.code == "UNAUTHENTICATED":
            return jsonify({
                "errors": [{
                    "code": "UNAUTHENTICATED",
                    "message": "Authentication is required.",
                }],
            }), 401
        logger.error("Current-user identity verification failed.")
        return jsonify({
            "errors": [{
                "code": "UPSTREAM_FAILURE",
                "message": "The current user could not be verified.",
            }],
        }), 502
