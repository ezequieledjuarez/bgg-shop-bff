import logging

from flask import jsonify, request

from ..dtos import AuthRequest, AuthResponse
from ..proxy import AuthInputError, UpstreamError, VerificationError, verification_caller


logger = logging.getLogger(__name__)


def auth_request(operation, success_status):
    try:
        payload = AuthRequest.from_payload(request.get_json(silent=True))
        result = AuthResponse.from_dict(operation(payload.payload))
        response = jsonify(result.to_dict())
        response.headers["Cache-Control"] = "no-store"
        return response, success_status
    except AuthInputError as exc:
        return jsonify({
            "errors": [{"code": "INVALID", "field": [exc.field], "message": str(exc)}],
        }), 400
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
        if exc.code == "EMAIL_NOT_VERIFIED":
            response = jsonify({
                "errors": [{
                    "code": exc.code,
                    "message": "Verify your email before signing in.",
                }],
            })
            response.headers["Cache-Control"] = "no-store"
            return response, 403
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


_VERIFICATION_ERRORS = {
    "INVALID_VERIFICATION_TOKEN": (400, "This verification link is invalid or has expired."),
    "INVALID": (400, "Enter a valid email address."),
    "VERIFICATION_UNAVAILABLE": (503, "Verification is temporarily unavailable. Try again later."),
    "UPSTREAM_FAILURE": (502, "The request could not be completed. Try again later."),
}


def _verification_response(body, status, extra_headers=None):
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    for name, value in (extra_headers or {}).items():
        response.headers[name] = value
    return response


def _verification_failure(exc, field=None, extra_headers=None):
    if exc.code == "RATE_LIMITED":
        headers = {**(extra_headers or {}), "Retry-After": str(exc.retry_after)}
        return _verification_response({
            "errors": [{"code": "RATE_LIMITED", "message": "Too many attempts. Try again later."}],
            "retry_after_seconds": exc.retry_after,
        }, 429, headers)
    status, message = _VERIFICATION_ERRORS[exc.code]
    error = {"code": exc.code, "message": message}
    if field and exc.code == "INVALID":
        error["field"] = [field]
    return _verification_response({"errors": [error]}, status, extra_headers)


def verification_request(operation, field, success_status, extra_headers=None):
    """POST-only verification endpoint; the caller identity comes from the direct peer."""
    if request.method != "POST":
        response = _verification_response({
            "errors": [{"code": "METHOD_NOT_ALLOWED", "message": "Only POST is supported."}],
        }, 405, extra_headers)
        response.headers["Allow"] = "POST"
        return response
    body = request.get_json(silent=True)
    value = body.get(field) if isinstance(body, dict) and set(body) == {field} else None
    try:
        caller = verification_caller(request.remote_addr)
        return _verification_response(operation(value, caller), success_status, extra_headers)
    except VerificationError as exc:
        return _verification_failure(exc, field, extra_headers)
    except UpstreamError:
        return _verification_failure(VerificationError("Verification upstream failed", "UPSTREAM_FAILURE"), field, extra_headers)
