import uuid

from flask import jsonify, request

from .. import auth, proxy
from ..proxy import UpstreamError


LIST_QUERY = """
query AdminOpSessions($userId: ID, $page: Int, $pageSize: Int) {
  adminOpSessions(userId: $userId, page: $page, pageSize: $pageSize) {
    items { id userId ops issuedAt expiresAt lastUsed revoked }
    hasNext userErrors { code }
  }
}
"""
MANAGE_MUTATION = """
mutation ManageOpSession($sessionId: ID!, $action: String!) {
  manageOpSession(sessionId: $sessionId, action: $action) { success userErrors { code } }
}
"""


def _error(status):
    response = jsonify({"error": "Operation session request failed"})
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _result(query, variables, field):
    try:
        payload = proxy._graphql_request(query, variables, token=request.headers.get("Authorization"))
        if not isinstance(payload, dict) or payload.get("errors"):
            return None, 502
        result = payload["data"][field]
        if not isinstance(result, dict) or not isinstance(result.get("userErrors"), list):
            return None, 502
        if result["userErrors"]:
            code = result["userErrors"][0].get("code")
            return None, {"UNAUTHENTICATED": 401, "FORBIDDEN": 403, "INVALID": 400, "NOT_FOUND": 404}.get(code, 502)
        return result, None
    except (UpstreamError, KeyError, TypeError, AttributeError, IndexError):
        return None, 502


@auth.admin_required
def list_sessions():
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "50"))
        user_id = request.args.get("user_id")
        if not 1 <= page <= 10000 or not 1 <= page_size <= 100 or (user_id is not None and int(user_id) < 1):
            return _error(400)
    except ValueError:
        return _error(400)
    result, status = _result(LIST_QUERY, {"userId": user_id, "page": page, "pageSize": page_size}, "adminOpSessions")
    if status:
        return _error(status)
    try:
        if not isinstance(result["items"], list) or type(result["hasNext"]) is not bool:
            return _error(502)
        items = []
        for row in result["items"]:
            identifier = str(uuid.UUID(row["id"]))
            if not isinstance(row["ops"], list) or not all(isinstance(op, str) for op in row["ops"]):
                return _error(502)
            if type(row["revoked"]) is not bool or not isinstance(row["issuedAt"], str):
                return _error(502)
            if any(value is not None and not isinstance(value, str) for value in (row["userId"], row["expiresAt"], row["lastUsed"])):
                return _error(502)
            items.append({"id": identifier, "user_id": row["userId"], "ops": row["ops"], "issued_at": row["issuedAt"],
                          "expires_at": row["expiresAt"], "last_used": row["lastUsed"], "revoked": row["revoked"]})
    except (ValueError, TypeError, KeyError, AttributeError):
        return _error(502)
    response = jsonify({"items": items, "has_next": result["hasNext"]})
    response.headers["Cache-Control"] = "no-store"
    return response, 200


@auth.admin_required
def manage_session(session_id, action):
    try:
        identifier = str(uuid.UUID(session_id))
    except (ValueError, TypeError):
        return _error(400)
    result, status = _result(MANAGE_MUTATION, {"sessionId": identifier, "action": action}, "manageOpSession")
    if status:
        return _error(status)
    if result.get("success") is not True:
        return _error(502)
    return "", 204, {"Cache-Control": "no-store"}