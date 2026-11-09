from flask import jsonify, request

from ..dtos import ProductPageDto, ProductQuery
from ..proxy import UpstreamError


def product_categories(list_categories_service):
    try:
        return jsonify(list_categories_service()), 200
    except UpstreamError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502


def product_publishers(list_publishers_service):
    try:
        publishers = list_publishers_service()
    except UpstreamError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502

    if not isinstance(publishers, list):
        return jsonify({"error": "upstream GraphQL request failed"}), 502
    names = set()
    for publisher in publishers:
        if not isinstance(publisher, dict):
            return jsonify({"error": "upstream GraphQL request failed"}), 502
        name = publisher.get("publisher")
        count = publisher.get("product_count")
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or len(name) > 250
            or name in names
            or type(count) is not int
            or count < 0
        ):
            return jsonify({"error": "upstream GraphQL request failed"}), 502
        names.add(name)
    return jsonify(publishers), 200


def products(list_products_service):
    publisher_values = request.args.getlist("publisher")
    if len(publisher_values) > 1:
        return jsonify({"error": "publisher must be supplied at most once"}), 400
    publisher = None
    if publisher_values:
        publisher = publisher_values[0].strip()
        if not publisher or len(publisher) > 250:
            return jsonify({"error": "publisher must contain 1 to 250 characters"}), 400

    query = ProductQuery.from_request_args(request.args)
    try:
        service_kwargs = query.as_service_kwargs()
        if publisher is not None:
            service_kwargs["publisher"] = publisher
        result = ProductPageDto.from_dict(
            list_products_service(**service_kwargs)
        )
        return jsonify(result.to_dict()), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502
