from flask import jsonify, request

from .. import auth
from ..proxy import UpstreamError
from ..services import admin_apply_coupon_preview as admin_apply_coupon_preview_service
from ..dtos.coupons import CouponApplyDto


@auth.admin_required
def admin_apply_coupon_preview(code):
    payload = request.get_json()
    try:
        dto = CouponApplyDto.from_payload(payload)
        validated = dto.validate()
        result = admin_apply_coupon_preview_service(code, **validated)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        return jsonify({"error": "upstream GraphQL request failed"}), 502
