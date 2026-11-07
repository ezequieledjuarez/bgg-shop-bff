import hashlib
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import jsonify, request

from .. import services
from .. import proxy
from ..chatbot.catalog import recommendation_request
from ..chatbot.guardrails import (
    classify_message,
    message_language,
    reply_for_classification,
    validate_message_payload,
)


_COOKIE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_INVALID_REQUEST = "Please provide a nonblank message of at most 2,000 characters."
_UNAUTHENTICATED = "Authentication is required for this chat session."
_NOT_FOUND = "The chat conversation was not found."
_UNAVAILABLE = "Chat is temporarily unavailable. Please try again."


def _error(code, status, message, retry_after=None):
    response = jsonify({"code": code, "error": message})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    if retry_after is not None:
        response.headers["Retry-After"] = str(max(1, int(retry_after)))
    return response


def _reply(
    conversation_id, answer, created_at=None, sources=None, recommendations=None
):
    response = jsonify(
        {
            "conversation_id": str(conversation_id),
            "answer": answer,
            "sources": sources or [],
            "recommendations": recommendations or [],
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _safe_source_url(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return value


def _validated_grounded_result(result):
    if not isinstance(result, dict):
        raise ValueError("Invalid grounded answer")
    answer = result.get("answer")
    raw_sources = result.get("sources", [])
    if not isinstance(answer, str) or not answer.strip() or not isinstance(raw_sources, list):
        raise ValueError("Invalid grounded answer")

    sources = []
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        title = source.get("title")
        if not isinstance(title, str):
            continue
        title = title.strip()
        if not title or len(title) > 200:
            continue
        validated_source = {"title": title}
        url = _safe_source_url(source.get("url"))
        if url is not None:
            validated_source["url"] = url
        sources.append(validated_source)
    return answer.strip(), sources


def _request_identity():
    authorization_present = "Authorization" in request.headers
    authorization = request.headers.get("Authorization") if authorization_present else None
    cookie_value = request.cookies.get("chat_session")
    return authorization_present, authorization, cookie_value


def _session_identity(cookie_value):
    session_digest = hashlib.sha256(
        f"chat:session:{cookie_value}".encode("utf-8")
    ).hexdigest()
    return f"chat:session:{session_digest}"


def _valid_bearer(authorization):
    return (
        isinstance(authorization, str)
        and authorization.startswith("Bearer ")
        and bool(authorization[7:].strip())
    )


def _valid_cookie(cookie_value):
    return isinstance(cookie_value, str) and _COOKIE_PATTERN.fullmatch(cookie_value) is not None


def _rate_limit_error(rate_limiter, identity):
    try:
        retry_after = rate_limiter(identity)
    except Exception:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)
    if retry_after is not None:
        return _error(
            "RATE_LIMITED",
            429,
            "Chat request limit reached. Please try again shortly.",
            retry_after=retry_after,
        )
    return None


def _rate_limit_identity(authorization_present, authorization, cookie_value):
    if authorization_present:
        if not _valid_bearer(authorization):
            raise proxy.UpstreamError(
                "Chat authentication is required", "UNAUTHENTICATED"
            )
        try:
            user_id = proxy.get_chat_user_id(authorization.strip())
        except proxy.UpstreamError:
            raise
        except Exception:
            raise proxy.UpstreamError("Chat identity lookup failed") from None
        return f"chat:user:{user_id}"
    if not _valid_cookie(cookie_value):
        raise proxy.UpstreamError(
            "Chat authentication is required", "UNAUTHENTICATED"
        )
    return _session_identity(cookie_value)


def _upstream_error(exc):
    if getattr(exc, "code", None) == "UNAUTHENTICATED":
        return _error("UNAUTHENTICATED", 401, _UNAUTHENTICATED)
    if getattr(exc, "code", None) == "NOT_FOUND":
        return _error("NOT_FOUND", 404, _NOT_FOUND)
    if getattr(exc, "code", None) == "INVALID_REQUEST":
        return _error("INVALID_REQUEST", 400, _INVALID_REQUEST)
    return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)


def create_conversation(create_service, rate_limiter, secure_cookie):
    authorization_present, authorization, cookie_value = _request_identity()
    new_cookie = False
    if not authorization_present and not cookie_value:
        cookie_value = secrets.token_urlsafe(32)
        new_cookie = True

    try:
        identity = _rate_limit_identity(
            authorization_present, authorization, cookie_value
        )
    except proxy.UpstreamError as exc:
        return _upstream_error(exc)
    limited = _rate_limit_error(rate_limiter, identity)
    if limited is not None:
        return limited

    token = authorization.strip() if authorization_present else None
    try:
        result = create_service(token=token, cookie_value=cookie_value)
        response = jsonify(result)
        response.status_code = 201
        response.headers["Cache-Control"] = "no-store"
        if new_cookie:
            response.set_cookie(
                "chat_session",
                cookie_value,
                httponly=True,
                samesite="Lax",
                secure=secure_cookie,
            )
        return response
    except proxy.ChatAssertionConfigurationError:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)
    except proxy.UpstreamError as exc:
        return _upstream_error(exc)
    except Exception:
        return _error("SERVICE_UNAVAILABLE", 503, _UNAVAILABLE)


def send_message(
    conversation_id, record_service, rate_limiter, answer_service_factory
):
    authorization_present, authorization, cookie_value = _request_identity()
    try:
        identity = _rate_limit_identity(
            authorization_present, authorization, cookie_value
        )
    except proxy.UpstreamError as exc:
        return _upstream_error(exc)
    limited = _rate_limit_error(rate_limiter, identity)
    if limited is not None:
        return limited

    message = validate_message_payload(request.get_json(silent=True))
    if message is None:
        return _error("INVALID_REQUEST", 400, _INVALID_REQUEST)
    unavailable = (
        "El chat no está disponible temporalmente. Inténtalo de nuevo."
        if message_language(message) == "es" else _UNAVAILABLE
    )

    classification = classify_message(message)
    if not authorization_present:
        try:
            proxy.validate_chat_assertion_configuration()
        except proxy.ChatAssertionConfigurationError:
            return _error("SERVICE_UNAVAILABLE", 503, unavailable)

    if classification != "in_scope":
        return _reply(
            conversation_id,
            reply_for_classification(classification, message),
        )

    token = authorization.strip() if authorization_present else None
    try:
        catalog_request = recommendation_request(message)
        if catalog_request is not None:
            answer = catalog_request["clarification"]
            recommendations = []
            if answer is None:
                recommendations = services.recommend_catalog_products(
                    catalog_request["filters"],
                    token=token,
                )
                answer = (
                    "Here are current products that match your request."
                    if recommendations
                    else "I couldn't find any matching products in the current catalog."
                )
                if message_language(message) == "es":
                    answer = (
                        "Estos son los productos actuales que coinciden con tu solicitud."
                        if recommendations
                        else "No encontré productos que coincidan en el catálogo actual."
                    )
            result = record_service(
                conversation_id=conversation_id,
                user_message=message,
                assistant_message=answer,
                token=token,
                cookie_value=cookie_value,
                sources=[],
            )
            conversation = result["conversation"]
            return _reply(
                conversation_id,
                answer,
                created_at=conversation.get("updated_at"),
                recommendations=recommendations,
            )

        grounded_service = answer_service_factory()
        answer, sources = _validated_grounded_result(
            grounded_service.answer(message)
        )
        result = record_service(
            conversation_id=conversation_id,
            user_message=message,
            assistant_message=answer,
            token=token,
            cookie_value=cookie_value,
            sources=sources,
        )
        conversation = result["conversation"]
        return _reply(
            conversation_id,
            answer,
            created_at=conversation.get("updated_at"),
            sources=sources,
        )
    except proxy.ChatAssertionConfigurationError:
        return _error("SERVICE_UNAVAILABLE", 503, unavailable)
    except proxy.UpstreamError as exc:
        if getattr(exc, "code", None) not in {"UNAUTHENTICATED", "NOT_FOUND", "INVALID_REQUEST"}:
            return _error("SERVICE_UNAVAILABLE", 503, unavailable)
        return _upstream_error(exc)
    except Exception:
        return _error("SERVICE_UNAVAILABLE", 503, unavailable)
