from datetime import datetime, timezone

from flask import jsonify, request

from .. import auth
from ..proxy import UpstreamError
from ..services import admin_list_audit as admin_list_audit_service

_TEXT_LIMITS = {"entity_type": 150, "entity_id": 64, "actor_id": 150, "action": 100, "cursor": 512}
_ALLOWED = set(_TEXT_LIMITS) | {"created_from", "created_to", "limit"}
_UPSTREAM_ERRORS = {
    "UNAUTHENTICATED": (401, "Authentication is required."),
    "FORBIDDEN": (403, "Administrative permission is required."),
}


def _invalid(field):
    return jsonify({"errors": [{"code": "INVALID", "field": field, "message": "The audit filter is invalid."}]}), 400


def _parse_date(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _filters():
    args = request.args
    for key in args:
        if key not in _ALLOWED or len(args.getlist(key)) != 1:
            return None, key if key in _ALLOWED else "query"
    filters = {}
    for key, maximum in _TEXT_LIMITS.items():
        if key in args:
            value = args[key]
            if not value.strip() or len(value) > maximum:
                return None, key
            filters[key] = value
    dates = {}
    for key in ("created_from", "created_to"):
        if key in args:
            dates[key] = _parse_date(args[key])
            if dates[key] is None:
                return None, key
            filters[key] = dates[key].isoformat()
    if len(dates) == 2 and dates["created_from"] > dates["created_to"]:
        return None, "created_from"
    if "limit" in args:
        raw = args["limit"]
        if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 100:
            return None, "limit"
        filters["limit"] = int(raw)
    return filters, None


@auth.admin_required
def admin_list_audit():
    filters, bad_field = _filters()
    if filters is None:
        response, status = _invalid(bad_field)
        response.status_code = status
    else:
        try:
            response = jsonify(
                admin_list_audit_service(
                    filters,
                    request.headers.get("Authorization"),
                    request.headers.get("X-Op-Key"),
                )
            )
            response.status_code = 200
        except UpstreamError as exc:
            if exc.user_error and exc.code in _UPSTREAM_ERRORS:
                status, message = _UPSTREAM_ERRORS[exc.code]
                response = jsonify({"error": message})
                response.status_code = status
            elif exc.user_error and exc.code == "INVALID":
                field = exc.field[0] if isinstance(exc.field, list) and exc.field else "query"
                response, status = _invalid(field)
                response.status_code = status
            else:
                response = jsonify({"error": "upstream GraphQL request failed"})
                response.status_code = 502
    response.headers["Cache-Control"] = "no-store"
    return response
