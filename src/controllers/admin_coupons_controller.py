from flask import jsonify, request

from .. import auth
from ..proxy import UpstreamError
from ..services import admin_apply_coupon_preview as admin_apply_coupon_preview_service
from ..services import (
    admin_create_coupon as admin_create_coupon_service,
    admin_list_coupons as admin_list_coupons_service,
    admin_update_coupon as admin_update_coupon_service,
)
from ..services import preview_coupon as preview_coupon_service
from ..dtos.coupons import (
    AdminCouponCreateDto,
    AdminCouponUpdateDto,
    CouponApplyDto,
)


def _admin_coupon_error(exc):
    if not exc.user_error:
        return jsonify({"error": "upstream GraphQL request failed"}), 502
    if exc.code == "SERVER_ERROR":
        return jsonify({"error": "upstream GraphQL request failed"}), 502
    status = {
        "UNAUTHENTICATED": 401,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "CODE_EXISTS": 409,
    }.get(exc.code, 400)
    message = {
        "UNAUTHENTICATED": "Authentication is required.",
        "FORBIDDEN": "Administrative permission is required.",
        "NOT_FOUND": "Coupon not found.",
        "CODE_EXISTS": "A coupon with this exact code already exists.",
    }.get(exc.code, "The coupon request is invalid.")
    if status in (401, 403, 404):
        return jsonify({"error": message}), status
    field = exc.field
    if isinstance(field, list):
        field = field[0] if field else None
    field = {
        "discountPercent": "discount_percent",
        "startsAt": "starts_at",
        "endsAt": "ends_at",
    }.get(field, field)
    error = {"code": exc.code, "message": message}
    if field:
        error["field"] = field
    return jsonify({"errors": [error]}), status


@auth.admin_required
def admin_list_coupons():
    try:
        response = jsonify(
            admin_list_coupons_service(
                request.headers.get("Authorization"),
                request.headers.get("X-Op-Key"),
            )
        )
        response.status_code = 200
    except UpstreamError:
        response = jsonify({"error": "upstream GraphQL request failed"})
        response.status_code = 502
    response.headers["Cache-Control"] = "no-store"
    return response


@auth.admin_required
def admin_create_coupon():
    try:
        dto = AdminCouponCreateDto.from_payload(request.get_json(silent=True))
        payload = dto.validate()
        payload["_auth_token"] = request.headers.get("Authorization")
        op_key = request.headers.get("X-Op-Key")
        if op_key:
            payload["_op_key"] = op_key
        response = jsonify(admin_create_coupon_service(payload))
        response.status_code = 201
    except ValueError as exc:
        response = jsonify({"error": str(exc)})
        response.status_code = 400
    except UpstreamError as exc:
        response, status = _admin_coupon_error(exc)
        response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@auth.admin_required
def admin_update_coupon(coupon_id):
    if type(coupon_id) is not int or not 1 <= coupon_id <= 2147483647:
        response = jsonify({"error": "coupon_id must be a positive integer"})
        response.status_code = 400
        response.headers["Cache-Control"] = "no-store"
        return response
    try:
        dto = AdminCouponUpdateDto.from_payload(request.get_json(silent=True))
        payload = dto.validate()
        payload["_auth_token"] = request.headers.get("Authorization")
        op_key = request.headers.get("X-Op-Key")
        if op_key:
            payload["_op_key"] = op_key
        response = jsonify(admin_update_coupon_service(coupon_id, payload))
        response.status_code = 200
    except ValueError as exc:
        response = jsonify({"error": str(exc)})
        response.status_code = 400
    except UpstreamError as exc:
        response, status = _admin_coupon_error(exc)
        response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def list_available_coupons(list_coupons_service):
    try:
        response = jsonify(list_coupons_service())
        response.status_code = 200
    except UpstreamError:
        response = jsonify({"error": "upstream GraphQL request failed"})
        response.status_code = 502
    response.headers["Cache-Control"] = "no-store"
    return response


def preview_current_cart_coupon():
    token = request.headers.get("Authorization")
    if not token:
        response = jsonify({"errors": [{"code": "UNAUTHENTICATED", "message": "Authentication is required."}]})
        response.status_code = 401
        response.headers["Cache-Control"] = "no-store"
        return response
    payload = request.get_json(silent=True)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"coupon_code"}
        or not isinstance(payload["coupon_code"], str)
        or not payload["coupon_code"]
        or len(payload["coupon_code"]) > 64
    ):
        response = jsonify({"errors": [{"code": "INVALID", "message": "A valid coupon_code is required."}]})
        response.status_code = 400
        response.headers["Cache-Control"] = "no-store"
        return response
    try:
        result = preview_coupon_service(payload["coupon_code"], token)
        response = jsonify(result)
        response.status_code = 200
    except UpstreamError as exc:
        code = exc.code
        status = 401 if code == "UNAUTHENTICATED" else 404 if code == "COUPON_NOT_FOUND" else 502
        body = (
            {"errors": [{"code": code, "message": str(exc)}]}
            if status < 500
            else {"error": "upstream GraphQL request failed"}
        )
        response = jsonify(body)
        response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


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
            err = {"field": exc.field, "code": exc.code, "message": "The coupon request is invalid."}
            return jsonify({"errors": [err]}), 400
        return jsonify({"error": "upstream GraphQL request failed"}), 502
