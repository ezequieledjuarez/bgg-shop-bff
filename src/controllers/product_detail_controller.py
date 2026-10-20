from flask import jsonify

from ..dtos import ProductDetailDto
from ..proxy import UpstreamError


def product_detail(slug, service):
    try:
        result = ProductDetailDto.from_dict(service(slug))
        return jsonify(result.to_dict()), 200
    except UpstreamError as exc:
        if exc.code == "PRODUCT_NOT_FOUND":
            return jsonify({"error": "PRODUCT_NOT_FOUND"}), 404
        return jsonify({"error": "upstream GraphQL request failed"}), 502
