from flask import jsonify, request

from ..dtos import ProductPageDto, ProductQuery
from ..proxy import UpstreamError


def product_categories(list_categories_service):
    try:
        return jsonify(list_categories_service()), 200
    except UpstreamError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502


def products(list_products_service):
    query = ProductQuery.from_request_args(request.args)
    try:
        result = ProductPageDto.from_dict(
            list_products_service(**query.as_service_kwargs())
        )
        return jsonify(result.to_dict()), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        return jsonify({
            "error": "upstream GraphQL request failed",
            "detail": str(exc),
        }), 502
