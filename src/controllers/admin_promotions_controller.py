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


@auth.admin_required
def admin_create_promotion():
    payload = request.get_json()
    try:
        dto = PromotionCreateDto.from_payload(payload)
        validated = dto.validate()
        result = admin_create_promotion_service(validated)
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        return jsonify({"error": "upstream GraphQL request failed"}), 502


@auth.admin_required
def admin_update_promotion(promotion_id):
    payload = request.get_json()
    try:
        dto = PromotionUpdateDto.from_payload(payload)
        validated = dto.validate()
        result = admin_update_promotion_service(promotion_id, validated)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        return jsonify({"error": "upstream GraphQL request failed"}), 502
