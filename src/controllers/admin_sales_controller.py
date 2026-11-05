from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from .. import auth
from ..proxy import UpstreamError
from ..services import admin_get_sales_categories, admin_get_sales_metrics

_ALLOWED_METRICS = {"from", "to", "category", "product_id"}
_REPEATABLE_METRICS = {"category", "product_id"}
_UPSTREAM_ERRORS = {
    "UNAUTHENTICATED": (401, "Authentication is required."),
    "FORBIDDEN": (403, "Administrative permission is required."),
}
_MAX_DATE_RANGE = timedelta(days=366)
_MAX_PRODUCT_ID = 2_147_483_647


def _invalid(field):
    return jsonify({"errors": [{"code": "INVALID", "field": field, "message": "The sales metrics filter is invalid."}]}), 400


def _parse_date(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _metrics_filters():
    args = request.args
    for key in args:
        if key not in _ALLOWED_METRICS:
            return None, "query"
        if key not in _REPEATABLE_METRICS and len(args.getlist(key)) != 1:
            return None, key

    has_from = "from" in args
    has_to = "to" in args
    from_date = _parse_date(args["from"]) if has_from else None
    if has_from and from_date is None:
        return None, "from"
    to_date = _parse_date(args["to"]) if has_to else None
    if has_to and to_date is None:
        return None, "to"
    if has_from != has_to:
        return None, "to" if has_from else "from"

    filters = {"categories": args.getlist("category") if "category" in args else None}
    if "product_id" in args:
        product_ids = []
        for value in args.getlist("product_id"):
            if not value.isascii() or not value.isdigit():
                return None, "product_id"
            product_id = int(value)
            if not 1 <= product_id <= _MAX_PRODUCT_ID:
                return None, "product_id"
            product_ids.append(product_id)
        filters["product_ids"] = product_ids
    else:
        filters["product_ids"] = None

    if has_from:
        if from_date >= to_date:
            return None, "from"
        if to_date - from_date > _MAX_DATE_RANGE:
            return None, "to"
        filters["from"] = from_date.isoformat()
        filters["to"] = to_date.isoformat()
    else:
        filters["from"] = None
        filters["to"] = None
    return filters, None


def _upstream_error_response(exc):
    if exc.user_error and exc.code in _UPSTREAM_ERRORS:
        status, message = _UPSTREAM_ERRORS[exc.code]
        return jsonify({"error": message}), status
    if exc.user_error and exc.code == "INVALID":
        field = exc.field[0] if isinstance(exc.field, list) and exc.field else "query"
        if field not in {"from", "to", "category", "product_id", "query"}:
            field = "query"
        response, status = _invalid(field)
        return response, status
    return jsonify({"error": "upstream GraphQL request failed"}), 502


@auth.admin_required
def get_admin_sales_metrics():
    filters, bad_field = _metrics_filters()
    if filters is None:
        response, status = _invalid(bad_field)
    else:
        try:
            response = jsonify(
                admin_get_sales_metrics(
                    filters,
                    request.headers.get("Authorization"),
                    request.headers.get("X-Op-Key"),
                )
            )
            status = 200
        except UpstreamError as exc:
            response, status = _upstream_error_response(exc)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@auth.admin_required
def get_admin_sales_categories():
    if request.args:
        response, status = _invalid("query")
    else:
        try:
            response = jsonify(
                admin_get_sales_categories(
                    request.headers.get("Authorization"),
                    request.headers.get("X-Op-Key"),
                )
            )
            status = 200
        except UpstreamError as exc:
            response, status = _upstream_error_response(exc)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response