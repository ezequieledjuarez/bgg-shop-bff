import logging

from flask import jsonify, request

from .. import auth
from ..proxy import UpstreamError
from ..services import admin_list_users, admin_update_user_privilege

logger = logging.getLogger(__name__)
_LIST_FIELDS = {"search", "cursor", "limit"}
_PRIVILEGES = {"is_staff", "is_superuser"}


def _invalid(field):
    return jsonify({
        "errors": [{
            "code": "INVALID",
            "field": field,
            "message": "The user management request is invalid.",
        }]
    }), 400


def _list_filters():
    args = request.args
    for key in args:
        if key not in _LIST_FIELDS or len(args.getlist(key)) != 1:
            return None, key if key in _LIST_FIELDS else "query"

    filters = {"search": None, "cursor": None, "limit": 50}
    if "search" in args:
        search = args["search"].strip()
        if not search or len(search) > 200:
            return None, "search"
        filters["search"] = search
    if "cursor" in args:
        cursor = args["cursor"]
        if not cursor or len(cursor) > 512:
            return None, "cursor"
        filters["cursor"] = cursor
    if "limit" in args:
        raw_limit = args["limit"]
        if not raw_limit.isascii() or not raw_limit.isdigit():
            return None, "limit"
        limit = int(raw_limit)
        if not 1 <= limit <= 100:
            return None, "limit"
        filters["limit"] = limit
    return filters, None


def _upstream_error(exc):
    if exc.user_error:
        status = {
            "UNAUTHENTICATED": 401,
            "FORBIDDEN": 403,
            "INVALID": 400,
            "NOT_FOUND": 404,
            "LAST_ACTIVE_SUPERUSER": 409,
        }.get(exc.code)
        if status is not None:
            if exc.code == "LAST_ACTIVE_SUPERUSER":
                return jsonify({"errors": [{
                    "code": "LAST_ACTIVE_SUPERUSER",
                    "message": "At least one active Superadmin must remain.",
                }]}), status
            if exc.code == "INVALID":
                field = exc.field[0] if isinstance(exc.field, list) and exc.field else "body"
                if field not in {"search", "cursor", "limit", "privilege", "enabled", "user_id", "query"}:
                    field = "body"
                return _invalid(field)
            message = {
                "UNAUTHENTICATED": "Authentication is required.",
                "FORBIDDEN": "Administrative permission is required.",
                "NOT_FOUND": "User not found.",
            }[exc.code]
            return jsonify({"error": message}), status
    return jsonify({"error": "upstream GraphQL request failed"}), 502


def _response(response, status):
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@auth.bearer_only
def list_users():
    filters, bad_field = _list_filters()
    if filters is None:
        response, status = _invalid(bad_field)
        return _response(response, status)
    try:
        return _response(
            jsonify(admin_list_users(filters, request.headers.get("Authorization"))),
            200,
        )
    except UpstreamError as exc:
        response, status = _upstream_error(exc)
        return _response(response, status)
    except Exception:
        logger.error("User listing request failed.")
        return _response(jsonify({"error": "upstream GraphQL request failed"}), 502)


@auth.bearer_only
def update_user_privilege(user_id):
    if not user_id:
        response, status = _invalid("user_id")
        return _response(response, status)
    body = request.get_json(silent=True)
    if (not isinstance(body, dict)
            or set(body) != {"privilege", "enabled"}
            or not isinstance(body.get("privilege"), str)
            or body["privilege"] not in _PRIVILEGES
            or type(body.get("enabled")) is not bool):
        response, status = _invalid("body")
        return _response(response, status)
    try:
        user = admin_update_user_privilege(
            user_id,
            body["privilege"],
            body["enabled"],
            request.headers.get("Authorization"),
        )
        return _response(jsonify(user), 200)
    except UpstreamError as exc:
        response, status = _upstream_error(exc)
        return _response(response, status)
    except Exception:
        logger.error("User privilege update request failed.")
        return _response(jsonify({"error": "upstream GraphQL request failed"}), 502)
