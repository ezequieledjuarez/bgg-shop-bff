from flask import jsonify, request

from ..dtos import AuthRequest, AuthResponse
from ..proxy import UpstreamError


def auth_request(operation, success_status):
    try:
        payload = AuthRequest.from_payload(request.get_json(silent=True))
        result = AuthResponse.from_dict(operation(payload.payload))
        return jsonify(result.to_dict()), success_status
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
