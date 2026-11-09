from flask import jsonify

from .. import proxy
from .chatbot_controller import (
    _UNAVAILABLE,
    _error,
    _rate_limit_error,
    _request_identity,
    _session_identity,
    _upstream_error,
    _valid_cookie,
)


def _request_scope(rate_limiter):
    authorization_present, authorization, cookie_value = _request_identity()

    if authorization_present:
        if not isinstance(authorization, str) or not authorization.strip():
            raise proxy.UpstreamError(
                "Chat authentication is required", "UNAUTHENTICATED"
            )
        token = authorization.strip()
        user_id = proxy.get_chat_user_id(token)
        identity = f"chat:user:{user_id}"
    else:
        if not _valid_cookie(cookie_value):
            raise proxy.UpstreamError(
                "Chat authentication is required", "UNAUTHENTICATED"
            )
        token = None
        identity = _session_identity(cookie_value)

    limited = _rate_limit_error(rate_limiter, identity)
    if limited is not None:
        return token, cookie_value, limited
    return token, cookie_value, None


def _conversation_query(conversation_id, token, cookie_value):
    query = """
    query ChatConversation($id: ID!) {
      chatConversation(id: $id) {
        conversation {
          id createdAt updatedAt expiresAt
          messages { id role content createdAt sources { title url } }
        }
        userErrors { code message field }
      }
    }
    """
    payload = proxy._graphql_request(
        query,
        {"id": conversation_id},
        token,
        extra_headers=proxy._chat_core_headers(token, cookie_value),
    )
    return proxy._chat_mutation_result(payload, "chatConversation")


def _raise_delete_errors(errors, *, user_errors=False):
    for error in errors or []:
        extensions = error.get("extensions") if isinstance(error, dict) else None
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if user_errors and code is None and isinstance(error, dict):
            code = error.get("code")
        if code == "UNAUTHENTICATED":
            raise proxy.UpstreamError(
                "Chat authentication is required", "UNAUTHENTICATED"
            )
        if code == "NOT_FOUND":
            raise proxy.UpstreamError("Chat conversation was not found", "NOT_FOUND")
        raise proxy.UpstreamError("Chat Core request failed")


def _delete_conversation(conversation_id, token, cookie_value):
    query = """
    mutation DeleteChatConversation($conversationId: ID!) {
      deleteChatConversation(conversationId: $conversationId) {
        success
        userErrors { code message field }
      }
    }
    """
    payload = proxy._graphql_request(
        query,
        {"conversationId": conversation_id},
        token,
        extra_headers=proxy._chat_core_headers(token, cookie_value),
    )
    if not isinstance(payload, dict):
        raise proxy.UpstreamError("Chat Core returned an invalid response")
    _raise_delete_errors(payload.get("errors"))

    result = (payload.get("data") or {}).get("deleteChatConversation")
    if not isinstance(result, dict):
        raise proxy.UpstreamError("Chat Core returned an invalid response")
    _raise_delete_errors(result.get("userErrors"), user_errors=True)
    if result.get("success") is not True:
        raise proxy.UpstreamError("Chat Core request failed")


def get_conversation(conversation_id, rate_limiter):
    try:
        token, cookie_value, limited = _request_scope(rate_limiter)
    except proxy.UpstreamError as exc:
        return _upstream_error(exc)
    except Exception:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)
    if limited is not None:
        return limited

    try:
        conversation = _conversation_query(conversation_id, token, cookie_value)
        response = jsonify({"conversation": conversation})
        response.headers["Cache-Control"] = "no-store"
        return response
    except proxy.ChatAssertionConfigurationError:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)
    except proxy.UpstreamError as exc:
        return _upstream_error(exc)
    except Exception:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)


def delete_conversation(conversation_id, rate_limiter):
    try:
        token, cookie_value, limited = _request_scope(rate_limiter)
    except proxy.UpstreamError as exc:
        return _upstream_error(exc)
    except Exception:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)
    if limited is not None:
        return limited

    try:
        _delete_conversation(conversation_id, token, cookie_value)
        return "", 204, {"Cache-Control": "no-store"}
    except proxy.ChatAssertionConfigurationError:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)
    except proxy.UpstreamError as exc:
        return _upstream_error(exc)
    except Exception:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)
