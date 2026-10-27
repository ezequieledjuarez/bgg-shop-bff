from flask import jsonify, request

from .. import auth
from ..proxy import UpstreamError
from ..services import (
    admin_list_products as admin_list_products_service,
    admin_create_product as admin_create_product_service,
    admin_update_product as admin_update_product_service,
    adjust_variant_stock as adjust_variant_stock_service,
)
from ..dtos.products import (
    AdminCreateProductDto,
    AdminUpdateProductDto,
    AdjustStockDto,
)


@auth.admin_required
def admin_list_products():
    args = request.args
    try:
        result = admin_list_products_service(
            page=args.get("page", 1),
            page_size=args.get("page_size", 20),
            q=args.get("q"),
        )
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        return jsonify({"error": "upstream GraphQL request failed", "detail": str(exc)}), 502


@auth.admin_required
def admin_create_product():
    payload = request.get_json()
    try:
        dto = AdminCreateProductDto.from_payload(payload)
        validated = dto.validate()
        result = admin_create_product_service(validated)
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        status = 502
        return jsonify({"error": "upstream GraphQL request failed"}), status


@auth.admin_required
def admin_update_product(product_id):
    payload = request.get_json()
    try:
        dto = AdminUpdateProductDto.from_payload(payload)
        validated = dto.validate()
        result = admin_update_product_service(product_id, validated)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        return jsonify({"error": "upstream GraphQL request failed"}), 502


@auth.admin_required
def admin_adjust_variant_stock(product_id, variant_id):
    payload = request.get_json()
    try:
        dto = AdjustStockDto.from_payload(payload)
        new_stock = dto.validate()
        result = adjust_variant_stock_service(product_id, variant_id, new_stock)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        return jsonify({"error": "upstream GraphQL request failed"}), 502
