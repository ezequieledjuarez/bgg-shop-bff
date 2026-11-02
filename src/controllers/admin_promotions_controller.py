from flask import jsonify, request

from .. import auth
from ..proxy import UpstreamError
from ..services import (
    admin_list_promotions as admin_list_promotions_service,
    admin_create_promotion as admin_create_promotion_service,
    admin_update_promotion as admin_update_promotion_service,
)
from ..dtos.promotions import PromotionCreateDto, PromotionUpdateDto


@auth.admin_required
def admin_list_promotions():
    try:
        result = admin_list_promotions_service()
        return jsonify(result), 200
    except UpstreamError as exc:
        return jsonify({"error": "upstream GraphQL request failed"}), 502


def _promotion_error(exc):
    if not exc.user_error or exc.code == "SERVER_ERROR":
        return jsonify({"error": "upstream GraphQL request failed"}), 502
    status = {"UNAUTHENTICATED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404}.get(exc.code, 400)
    message = {
        "UNAUTHENTICATED": "Authentication is required.",
        "FORBIDDEN": "Administrative permission is required.",
        "NOT_FOUND": "Promotion not found.",
    }.get(exc.code, "The promotion request is invalid.")
    if status in (401, 403, 404):
        return jsonify({"error": message}), status
    field = exc.field[0] if isinstance(exc.field, list) and exc.field else exc.field
    error = {"code": exc.code, "message": message}
    if isinstance(field, str):
        error["field"] = field
    return jsonify({"errors": [error]}), 400


@auth.admin_required
def admin_create_promotion():
    payload = request.get_json()
    try:
        dto = PromotionCreateDto.from_payload(payload)
        validated = dto.validate()
        token = request.headers.get("Authorization")
        if isinstance(validated, dict):
            validated["_auth_token"] = token
            op_key = request.headers.get("X-Op-Key")
            if op_key:
                validated["_op_key"] = op_key
        result = admin_create_promotion_service(validated)
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        return _promotion_error(exc)


@auth.admin_required
def admin_update_promotion(promotion_id):
    payload = request.get_json()
    try:
        dto = PromotionUpdateDto.from_payload(payload)
        validated = dto.validate()
        token = request.headers.get("Authorization")
        if isinstance(validated, dict):
            validated["_auth_token"] = token
            op_key = request.headers.get("X-Op-Key")
            if op_key:
                validated["_op_key"] = op_key
        result = admin_update_promotion_service(promotion_id, validated)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        return _promotion_error(exc)
