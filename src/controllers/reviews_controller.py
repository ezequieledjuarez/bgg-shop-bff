from flask import jsonify, request

from .. import auth, catalog_cache
from ..dtos import CreateReviewRequestDto, CreateReviewResponseDto
from ..proxy import UpstreamError


_REVIEW_STATUSES = {"PENDING", "ACCEPTED", "REJECTED"}
_REVIEW_ACTIONS = {"ACCEPT", "REJECT", "DELETE"}
_MODERATION_ERRORS = {
    "UNAUTHENTICATED": (401, "Authentication is required."),
    "FORBIDDEN": (403, "Administrative permission is required."),
    "REVIEW_NOT_FOUND": (404, "Review not found."),
    "INVALID_TRANSITION": (409, "Review action is not valid for the current state."),
}


def _moderation_response(payload, status):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _invalid_moderation_request(field):
    return _moderation_response(
        {"errors": [{
            "code": "INVALID",
            "field": field,
            "message": "The review request is invalid.",
        }]},
        400,
    )


def _positive_integer(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        return None
    parsed = int(value)
    return parsed if 1 <= parsed <= 2147483647 else None


def _queue_filters():
    allowed = {"status", "page", "page_size"}
    for key in request.args:
        if key not in allowed or len(request.args.getlist(key)) != 1:
            return None, key if key in allowed else "query"

    status = request.args.get("status")
    if status is not None and status not in _REVIEW_STATUSES:
        return None, "status"

    filters = {"status": status}
    for key, default, maximum in (("page", 1, 2147483647), ("page_size", 50, 100)):
        raw = request.args.get(key)
        if raw is None:
            filters["pageSize" if key == "page_size" else key] = default
            continue
        parsed = _positive_integer(raw)
        if parsed is None or parsed > maximum:
            return None, key
        filters["pageSize" if key == "page_size" else key] = parsed
    return filters, None


@auth.review_moderator_required
def admin_list_reviews(service):
    filters, bad_field = _queue_filters()
    if filters is None:
        return _invalid_moderation_request(bad_field)
    try:
        result = service(filters, request.headers.get("Authorization"))
        response = jsonify(result)
        response.status_code = 200
    except UpstreamError as exc:
        status, message = _MODERATION_ERRORS.get(
            exc.code, (502, "upstream GraphQL request failed")
        ) if exc.user_error else (502, "upstream GraphQL request failed")
        response = jsonify({"error": message})
        response.status_code = status
    except Exception:
        response = jsonify({"error": "upstream GraphQL request failed"})
        response.status_code = 502
    response.headers["Cache-Control"] = "no-store"
    return response


@auth.review_moderator_required
def admin_moderate_review(review_id, service):
    if type(review_id) is not int or not 1 <= review_id <= 2147483647:
        return _invalid_moderation_request("review_id")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"action"}:
        return _invalid_moderation_request("action")
    action = payload.get("action")
    if not isinstance(action, str) or action not in _REVIEW_ACTIONS:
        return _invalid_moderation_request("action")
    try:
        result = service(review_id, action, request.headers.get("Authorization"))
    except UpstreamError as exc:
        status, message = _MODERATION_ERRORS.get(
            exc.code, (502, "upstream GraphQL request failed")
        ) if exc.user_error else (502, "upstream GraphQL request failed")
        return _moderation_response({"error": message}, status)
    except Exception:
        return _moderation_response(
            {"error": "upstream GraphQL request failed"},
            502,
        )

    cache_refresh_pending = False
    for _ in range(2):
        try:
            catalog_cache.invalidate_catalog_cache(review_id)
            cache_refresh_pending = False
            break
        except Exception:
            cache_refresh_pending = True

    return _moderation_response(
        {
            "review_id": result["review_id"],
            "status": result["status"],
            "deleted": result["deleted"],
            "publicly_visible": result["publicly_visible"],
            "cache_refresh_pending": cache_refresh_pending,
        },
        200,
    )


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
        public_errors = {
            "UNAUTHENTICATED": (401, "Authentication is required."),
            "PRODUCT_NOT_FOUND": (404, "The requested game does not exist."),
            "REVIEW_ALREADY_EXISTS": (409, "You already reviewed this game."),
            "RATING_OUT_OF_RANGE": (400, "Rating must be between 1 and 5."),
            "BODY_REQUIRED": (400, "Review text is required."),
            "BODY_TOO_LONG": (400, "Review text must not exceed 2000 characters."),
        }
        if exc.code in public_errors:
            status, message = public_errors[exc.code]
            return jsonify({"errors": [{"code": exc.code, "message": message}]}), status
        return jsonify({
            "errors": [{
                "code": "UPSTREAM_ERROR",
                "message": "upstream GraphQL request failed",
            }],
        }), 502
