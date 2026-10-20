from flask import jsonify, request

from ..dtos import CreateReviewRequestDto, CreateReviewResponseDto
from ..proxy import UpstreamError


def create_review(slug, service):
    try:
        payload = CreateReviewRequestDto.from_payload(request.get_json(silent=True))
        if not isinstance(payload.rating, int) or isinstance(payload.rating, bool):
            raise ValueError("rating must be an integer")
        if payload.rating < 1 or payload.rating > 5:
            raise ValueError("rating must be between 1 and 5")
        if not isinstance(payload.body, str) or not payload.body.strip():
            raise ValueError("body is required")
        if len(payload.body.strip()) > 2000:
            raise ValueError("body must not exceed 2000 characters")
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"errors": [{"code": "UNAUTHENTICATED"}]}), 401
        result = service(slug, payload.rating, payload.body.strip(), token)
        return jsonify(CreateReviewResponseDto.from_dict(result).to_dict()), 201
    except ValueError as exc:
        return jsonify({"errors": [{"code": "INVALID", "message": str(exc)}]}), 400
    except UpstreamError as exc:
        statuses = {
            "UNAUTHENTICATED": 401,
            "PRODUCT_NOT_FOUND": 404,
            "REVIEW_ALREADY_EXISTS": 409,
            "RATING_OUT_OF_RANGE": 400,
            "BODY_REQUIRED": 400,
            "BODY_TOO_LONG": 400,
        }
        if exc.code in statuses:
            return jsonify({"errors": [{"code": exc.code, "message": str(exc)}]}), statuses[exc.code]
        return jsonify({
            "errors": [{
                "code": "UPSTREAM_ERROR",
                "message": "upstream GraphQL request failed",
            }],
        }), 502
