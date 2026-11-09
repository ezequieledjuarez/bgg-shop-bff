import json
import re
import os
import uuid
import hashlib
import hmac
import time
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

import jwt
import requests
import logging


MAX_PAGE_SIZE = 200
DEFAULT_GRAPHQL_URL = "http://localhost:8000/graphql/"

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

class UpstreamError(Exception):
    def __init__(self, message, code="UPSTREAM_ERROR", field=None, user_error=False, response_text=None, context=None):
        super().__init__(message)
        self.code = code
        self.field = field
        self.user_error = user_error


class ChatAssertionConfigurationError(Exception):
    pass


def _required_text(payload, name, minimum=1, maximum=254):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    value = value.strip()
    if len(value) < minimum or len(value) > maximum:
        raise ValueError(f"{name} has an invalid length")
    return value


def _auth_request(query, variables):
    request_id = str(uuid.uuid4())
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": variables},
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code in (301, 302, 303, 307, 308):
            raise UpstreamError("Authentication upstream returned a redirect")
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        logger.error("Authentication upstream request failed (request_id=%s)", request_id)
        raise UpstreamError("Authentication upstream request failed", context={"request_id": request_id}) from None
    if payload.get("errors"):
        logger.error("Authentication GraphQL request returned errors (request_id=%s)", request_id)
        raise UpstreamError("GraphQL upstream returned errors")
    return payload


def _auth_result(payload, field):
    result = (payload.get("data") or {}).get(field)
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid authentication payload")
    errors = result.get("errors") or []
    if errors:
        code = errors[0].get("code")
        if code in ("DUPLICATE_EMAIL", "EMAIL_EXISTS", "UNIQUE"):
            raise UpstreamError("The email is already registered", "EMAIL_EXISTS")
        if code in ("INVALID_CREDENTIALS", "INVALID"):
            raise UpstreamError("Invalid credentials", "INVALID_CREDENTIALS")
        raise UpstreamError("GraphQL authentication failed")
    user = result.get("user")
    if not isinstance(user, dict):
        raise UpstreamError("GraphQL upstream returned no authenticated user")
    response = {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "first_name": user["firstName"],
            "last_name": user["lastName"],
            "is_active": user["isActive"],
        },
    }
    tokens = result.get("tokens")
    if tokens is not None:
        response["session"] = {
            "access_token": tokens.get("token"),
            "refresh_token": tokens.get("refreshToken"),
            "csrf_token": tokens.get("csrfToken"),
        }
        # Include op_key if Core returned one-time operations key
        op_key = tokens.get("opKey") or tokens.get("op_key")
        if op_key:
            response["session"]["op_key"] = op_key
            response["session"]["op_key_expires_at"] = tokens.get("opKeyExpiresAt")
            response["session"]["ops"] = tokens.get("ops")
    return response


def register_account(payload):
    email = _required_text(payload, "email").lower()
    password = _required_text(payload, "password", 8, 128)
    first_name = _required_text(payload, "first_name", 1, 150)
    last_name = _required_text(payload, "last_name", 1, 150)
    if "@" not in email:
        raise ValueError("email must be valid")
    query = """
    mutation Register($input: RegisterInput!) {
      register(input: $input) {
        user { id email firstName lastName isActive }
        tokens { token refreshToken csrfToken }
        errors { field code message }
      }
    }
    """
    return _auth_result(_auth_request(query, {
        "input": {"email": email, "password": password, "firstName": first_name, "lastName": last_name}
    }), "register")


def authenticate_account(payload):
    email = _required_text(payload, "email").lower()
    password = _required_text(payload, "password", 1, 128)
    if "@" not in email:
        raise ValueError("email must be valid")
    query = """
    mutation Login($input: LoginInput!) {
      login(input: $input) {
        user { id email firstName lastName isActive }
                tokens { token refreshToken csrfToken opKey opKeyExpiresAt ops }
        errors { field code message }
      }
    }
    """
    login_input = {"email": email, "password": password}
    if payload.get("guest_cart_id"):
        login_input["guestCartId"] = payload["guest_cart_id"]
    result = _auth_result(_auth_request(query, {"input": login_input}), "login")
    if "session" not in result:
        raise UpstreamError("GraphQL login returned no session")
    return result


def revoke_operation_key(op_key):
    secret = os.getenv("OPKEY_INTERNAL_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise UpstreamError("Operation key revocation unavailable")
    try:
        response = requests.post(
            f'{os.getenv("SALEOR_BASE_URL", "http://localhost:8000")}/internal/op-revoke',
            json={"op_key": op_key, "reason": "logout"}, headers={"X-Internal-Secret": secret}, timeout=3, allow_redirects=False,
        )
        if response.status_code != 200:
            raise UpstreamError("Operation key revocation failed")
        payload = response.json()
        if not isinstance(payload, dict) or type(payload.get("revoked")) is not int or payload["revoked"] < 0:
            raise UpstreamError("Operation key revocation failed")
    except (requests.RequestException, ValueError):
        raise UpstreamError("Operation key revocation failed") from None


def _pagination_value(value, name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a positive integer")
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    # Enforce maximum page size: clamp to MAX_PAGE_SIZE instead of raising.
    if name == "page_size" and parsed > MAX_PAGE_SIZE:
        try:
            logger.warning("Requested page_size %s exceeds MAX_PAGE_SIZE %s; clamping to max", parsed, MAX_PAGE_SIZE)
        except Exception:
            pass
        return MAX_PAGE_SIZE
    return parsed


def _optional_integer(value, name, minimum, maximum):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if parsed < minimum or (maximum is not None and parsed > maximum):
        limit = (
            f" between {minimum} and {maximum}"
            if maximum is not None
            else f" greater than or equal to {minimum}"
        )
        raise ValueError(f"{name} must be{limit}")
    return parsed


def _optional_decimal(value, name):
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if parsed < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
    return parsed


def list_product_categories():
    payload = _graphql_request("query ProductCategories { productCategories }", {})
    data = payload.get("data")
    categories = data.get("productCategories") if isinstance(data, dict) else None
    if payload.get("errors") or not isinstance(categories, list) or not all(
        isinstance(item, str) and item.strip() for item in categories
    ):
        raise UpstreamError("GraphQL upstream returned invalid categories")
    return categories


def list_product_publishers():
    payload = _graphql_request(
        "query ProductPublishers { productPublishers { publisher productCount } }",
        {},
    )
    data = payload.get("data")
    facets = data.get("productPublishers") if isinstance(data, dict) else None
    if payload.get("errors") or not isinstance(facets, list):
        raise UpstreamError("GraphQL upstream returned invalid publisher facets")

    result = []
    seen = set()
    for facet in facets:
        if not isinstance(facet, dict):
            raise UpstreamError("GraphQL upstream returned invalid publisher facets")
        publisher = facet.get("publisher")
        product_count = facet.get("productCount")
        if (
            not isinstance(publisher, str)
            or not publisher
            or publisher != publisher.strip()
            or len(publisher) > 250
            or publisher in seen
            or type(product_count) is not int
            or product_count < 0
        ):
            raise UpstreamError("GraphQL upstream returned invalid publisher facets")
        seen.add(publisher)
        result.append({"publisher": publisher, "product_count": product_count})
    return result


def list_products(
    page=1,
    page_size=50,
    search=None,
    year_published=None,
    min_players=None,
    max_players=None,
    category_id=None,
    category_name=None,
    price_min=None,
    price_max=None,
    token=None,
    publisher=None,
):
    page = _pagination_value(page, "page")
    page_size = _pagination_value(page_size, "page_size")
    if search is not None and (not str(search).strip() or len(str(search)) > 200):
        raise ValueError("search must contain between 1 and 200 characters")
    if category_name is not None and not str(category_name).strip():
        raise ValueError("category_name must not be blank")
    if publisher is not None:
        publisher = str(publisher).strip()
        if not publisher or len(publisher) > 250:
            raise ValueError("publisher must contain 1 to 250 characters")

    filters = {
        "search": search,
        "publisher": publisher,
        "yearPublished": _optional_integer(year_published, "year_published", 0, 9999),
        "minPlayers": _optional_integer(min_players, "min_players", 1, 999),
        "maxPlayers": _optional_integer(max_players, "max_players", 1, 999),
        "categoryId": _optional_integer(category_id, "category_id", 1, None),
        "categoryName": str(category_name).strip() if category_name is not None else None,
        "priceMin": _optional_decimal(price_min, "price_min"),
        "priceMax": _optional_decimal(price_max, "price_max"),
    }
    if filters["minPlayers"] is not None and filters["maxPlayers"] is not None:
        if filters["minPlayers"] > filters["maxPlayers"]:
            raise ValueError("min_players must be less than or equal to max_players")
    if filters["priceMin"] is not None and filters["priceMax"] is not None:
        if filters["priceMin"] > filters["priceMax"]:
            raise ValueError("price_min must be less than or equal to price_max")

    # GraphQL query for product listing (always defined)
    query = """
    query Products(
        $page: Int!, $pageSize: Int!, $search: String, $publisher: String, $yearPublished: Int,
        $minPlayers: Int, $maxPlayers: Int, $categoryId: Int, $categoryName: String,
        $priceMin: Float, $priceMax: Float
    ) {
        products(
            page: $page, pageSize: $pageSize, search: $search, publisher: $publisher,
            yearPublished: $yearPublished, minPlayers: $minPlayers,
            maxPlayers: $maxPlayers, categoryId: $categoryId, categoryName: $categoryName,
            priceMin: $priceMin, priceMax: $priceMax
        ) {
            items {
                bggId
                name
                releaseYear
                minPlayers
                maxPlayers
                playingTimeMinutes
                minAge
                weight
                category
                price
                quantity
                publisher
                imageUrl
            }
            page
            pageSize
            total
            totalPages
        }
    }
    """
    request_id = str(uuid.uuid4())
    headers = {"Authorization": token} if token else {}
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": {"page": page, "pageSize": page_size, **filters}},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        logger.error("Products upstream request failed (request_id=%s)", request_id)
        raise UpstreamError("Products upstream request failed", context={"request_id": request_id}) from None

    if payload.get("errors"):
        logger.error("Products GraphQL request returned errors (request_id=%s)", request_id)
        raise UpstreamError("GraphQL upstream returned errors")

    products = (payload.get("data") or {}).get("products")
    if not products:
        logger.error("Products GraphQL response contained no products (request_id=%s)", request_id)
        raise UpstreamError("GraphQL upstream returned no products data")

    try:
        return {
            "items": [
                {
                    "bgg_id": item["bggId"],
                    "name": item["name"],
                    "release_year": item["releaseYear"],
                    "min_players": item["minPlayers"],
                    "max_players": item["maxPlayers"],
                    "playing_time_minutes": item["playingTimeMinutes"],
                    "min_age": item["minAge"],
                    "weight": item["weight"],
                    "category": item["category"],
                    "price": item["price"],
                    "quantity": item["quantity"],
                    "publisher": item["publisher"],
                    "image_url": item["imageUrl"],
                }
                for item in products["items"]
            ],
            "page": products["page"],
            "page_size": products["pageSize"],
            "total": products["total"],
            "total_pages": products["totalPages"],
        }
    except (KeyError, TypeError):
        logger.error("Invalid products payload (request_id=%s)", request_id)
        raise UpstreamError("GraphQL upstream returned an invalid product payload") from None
    # end of list_products


def graphql_auth_headers(token=None, op_key=None):
    headers = {}
    if token:
        headers["Authorization"] = token
    from flask import g, has_request_context, request
    if has_request_context():
        incoming_key = request.headers.get("X-Op-Key")
        selected_key = op_key or incoming_key
        secret = os.getenv("OPKEY_INTERNAL_SECRET", "")
        if (incoming_key and selected_key == incoming_key and getattr(g, "op_session_valid", False)
                and request.path.startswith("/api/v1/admin/") and len(secret.encode("utf-8")) >= 32):
            headers.update({
                "X-Op-Key": selected_key,
                "X-Internal-Secret": secret,
                "X-Op-Method": request.method,
                "X-Op-Path": request.path,
            })
    return headers


def _graphql_request(
    query,
    variables,
    token=None,
    op_key=None,
    map_wishlist_errors=False,
    extra_headers=None,
):
    request_id = str(uuid.uuid4())
    headers = graphql_auth_headers(token, op_key)
    if extra_headers:
        headers.update(extra_headers)
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code in (301, 302, 303, 307, 308):
            raise UpstreamError("GraphQL upstream returned a redirect")
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        logger.error("GraphQL upstream request failed (request_id=%s)", request_id)
        raise UpstreamError("GraphQL upstream request failed", context={"request_id": request_id}) from None
    if not isinstance(payload, dict):
        raise UpstreamError("GraphQL upstream returned an invalid response")
    if map_wishlist_errors:
        for error in payload.get("errors") or []:
            if not isinstance(error, dict):
                continue
            extensions = error.get("extensions")
            code = extensions.get("code") if isinstance(extensions, dict) else None
            message = error.get("message")
            if code == "UNAUTHENTICATED" or message == "Authentication is required.":
                raise UpstreamError("Authentication is required.", "UNAUTHENTICATED")
            if code == "PRODUCT_NOT_FOUND" or message == "Product not found.":
                raise UpstreamError("The requested game does not exist.", "PRODUCT_NOT_FOUND")
    return payload


def _chat_assertion_secret():
    secret = os.getenv("CHAT_ASSERTION_SECRET", "")
    if (
        not isinstance(secret, str)
        or not secret.isascii()
        or len(secret) < 32
        or len(set(secret)) < 16
        or any(
            candidate
            and hmac.compare_digest(secret, candidate)
            for candidate in (
                os.getenv("SECRET_KEY", ""),
                os.getenv("OPKEY_INTERNAL_SECRET", ""),
                os.getenv("CATALOG_EVENTS_HMAC_SECRET", ""),
            )
        )
    ):
        raise ChatAssertionConfigurationError
    return secret


def validate_chat_assertion_configuration():
    _chat_assertion_secret()


def _chat_assertion(cookie_value):
    secret = _chat_assertion_secret()

    issued_at = int(time.time())
    claims = {
        "iss": "bgg-shop-bff",
        "aud": "bgg-shop-core",
        "sub": hashlib.sha256(cookie_value.encode("utf-8")).hexdigest(),
        "scope": "chat:conversations",
        "iat": issued_at,
        "exp": issued_at + 60,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        claims,
        secret,
        algorithm="HS256",
        headers={"typ": "chat-assertion"},
    )


def _chat_core_headers(token, cookie_value):
    if token is not None:
        return {}
    if not isinstance(cookie_value, str) or not cookie_value:
        raise ChatAssertionConfigurationError
    return {"X-Chat-Assertion": _chat_assertion(cookie_value)}


def get_chat_user_id(token):
    payload = _graphql_request(
        "query ChatRateLimitIdentity { me { id } }",
        {},
        token=token,
    )
    for error in payload.get("errors") or []:
        if not isinstance(error, dict):
            raise UpstreamError("Chat identity lookup failed")
        extensions = error.get("extensions")
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if (
            code == "UNAUTHENTICATED"
            or error.get("message") == "Authentication is required."
        ):
            raise UpstreamError("Chat authentication is required", "UNAUTHENTICATED")
        raise UpstreamError("Chat identity lookup failed")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise UpstreamError("Chat identity lookup returned an invalid response")
    user = data.get("me")
    if user is None:
        raise UpstreamError("Chat authentication is required", "UNAUTHENTICATED")
    if not isinstance(user, dict):
        raise UpstreamError("Chat identity lookup returned an invalid response")
    user_id = user.get("id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise UpstreamError("Chat identity lookup returned an invalid response")
    return user_id


def _chat_conversation_from_core(conversation):
    if not isinstance(conversation, dict):
        raise UpstreamError("Chat Core returned an invalid response")
    try:
        messages = []
        for message in conversation["messages"]:
            messages.append(
                {
                    "id": str(message["id"]),
                    "role": str(message["role"]).lower(),
                    "content": message["content"],
                    "created_at": message["createdAt"],
                    "sources": [
                        {
                            "title": source["title"],
                            **(
                                {"url": source["url"]}
                                if source.get("url") is not None
                                else {}
                            ),
                        }
                        for source in message.get("sources") or []
                    ],
                }
            )
        return {
            "id": str(conversation["id"]),
            "messages": messages,
            "created_at": conversation["createdAt"],
            "updated_at": conversation["updatedAt"],
            "expires_at": conversation["expiresAt"],
        }
    except (KeyError, TypeError):
        raise UpstreamError("Chat Core returned an invalid response") from None


def _chat_mutation_result(payload, field):
    if not isinstance(payload, dict):
        raise UpstreamError("Chat Core returned an invalid response")
    for error in payload.get("errors") or []:
        extensions = error.get("extensions") if isinstance(error, dict) else None
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if code == "UNAUTHENTICATED":
            raise UpstreamError("Chat authentication is required", code)
        if code == "NOT_FOUND":
            raise UpstreamError("Chat conversation was not found", code)
        raise UpstreamError("Chat Core request failed")

    result = (payload.get("data") or {}).get(field)
    if not isinstance(result, dict):
        raise UpstreamError("Chat Core returned an invalid response")
    user_errors = result.get("userErrors") or []
    if user_errors:
        code = user_errors[0].get("code") if isinstance(user_errors[0], dict) else None
        if code == "UNAUTHENTICATED":
            raise UpstreamError("Chat authentication is required", code)
        if code == "NOT_FOUND":
            raise UpstreamError("Chat conversation was not found", code)
        if code == "INVALID":
            raise UpstreamError("Chat request was rejected", "INVALID_REQUEST")
        raise UpstreamError("Chat Core request failed")
    return _chat_conversation_from_core(result.get("conversation"))


def create_chat_conversation(token=None, cookie_value=None):
    query = """
    mutation CreateChatConversation {
      createChatConversation {
        conversation {
          id createdAt updatedAt expiresAt
          messages { id role content createdAt sources { title url } }
        }
        userErrors { code message field }
      }
    }
    """
    payload = _graphql_request(
        query,
        {},
        token,
        extra_headers=_chat_core_headers(token, cookie_value),
    )
    return {"conversation": _chat_mutation_result(payload, "createChatConversation")}


def record_chat_exchange(
    conversation_id,
    user_message,
    assistant_message,
    token=None,
    cookie_value=None,
    sources=None,
):
    query = """
    mutation RecordChatExchange(
      $conversationId: ID!
      $userMessage: String!
      $assistantMessage: String!
      $sources: [ChatSourceInput!]
    ) {
      recordChatExchange(
        conversationId: $conversationId
        userMessage: $userMessage
        assistantMessage: $assistantMessage
        sources: $sources
      ) {
        conversation {
          id createdAt updatedAt expiresAt
          messages { id role content createdAt sources { title url } }
        }
        userErrors { code message field }
      }
    }
    """
    payload = _graphql_request(
        query,
        {
            "conversationId": conversation_id,
            "userMessage": user_message,
            "assistantMessage": assistant_message,
            "sources": sources if sources is not None else [],
        },
        token,
        extra_headers=_chat_core_headers(token, cookie_value),
    )
    return {"conversation": _chat_mutation_result(payload, "recordChatExchange")}


def get_product_detail(slug):
    query = """
    query ProductBySlug($slug: String!) {
      productBySlug(slug: $slug) {
        bggId name releaseYear minPlayers maxPlayers playingTimeMinutes minAge
        weight category price quantity publisher imageUrl
        reviewSummary { approvedReviewCount averageRating }
        approvedReviews { rating body createdAt }
      }
    }
    """
    payload = _graphql_request(query, {"slug": slug})
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    product = (payload.get("data") or {}).get("productBySlug")
    if product is None:
        raise UpstreamError("The requested game does not exist", "PRODUCT_NOT_FOUND")
    try:
        return {
            "bgg_id": product["bggId"],
            "name": product["name"],
            "weight": product["weight"],
            "category": product["category"],
            "price": product["price"],
            "quantity": product["quantity"],
            "publisher": product["publisher"],
            "release_year": product["releaseYear"],
            "min_players": product["minPlayers"],
            "max_players": product["maxPlayers"],
            "playing_time_minutes": product["playingTimeMinutes"],
            "min_age": product["minAge"],
            "image_url": product["imageUrl"],
            "review_summary": {
                "approved_review_count": product["reviewSummary"]["approvedReviewCount"],
                "average_rating": product["reviewSummary"]["averageRating"],
            },
            "approved_reviews": [
                {"rating": item["rating"], "body": item["body"], "created_at": item["createdAt"]}
                for item in product["approvedReviews"]
            ],
        }
    except (KeyError, TypeError) as exc:
        raise UpstreamError("GraphQL upstream returned an invalid product payload") from exc


def get_product_by_bgg_id(bgg_id, token=None):
    query_direct = """
    query ProductByBggId($bggId: Int!) {
      productByBggId(bggId: $bggId) {
        bggId name releaseYear minPlayers maxPlayers playingTimeMinutes minAge
        weight category price quantity publisher imageUrl
        reviewSummary { approvedReviewCount averageRating }
        approvedReviews { rating body createdAt }
      }
    }
    """
    payload = _graphql_request(query_direct, {"bggId": int(bgg_id)}, token)
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    data = payload.get("data")
    if not isinstance(data, dict) or "productByBggId" not in data:
        raise UpstreamError("GraphQL upstream returned an invalid product payload")
    product = data["productByBggId"]
    if product is None:
        raise UpstreamError("The requested game does not exist", "PRODUCT_NOT_FOUND")
    try:
        return {
            "bgg_id": product["bggId"],
            "name": product["name"],
            "weight": product["weight"],
            "category": product["category"],
            "price": product["price"],
            "quantity": product["quantity"],
            "publisher": product["publisher"],
            "release_year": product["releaseYear"],
            "min_players": product["minPlayers"],
            "max_players": product["maxPlayers"],
            "playing_time_minutes": product["playingTimeMinutes"],
            "min_age": product["minAge"],
            "image_url": product["imageUrl"],
            "review_summary": {
                "approved_review_count": product["reviewSummary"]["approvedReviewCount"],
                "average_rating": product["reviewSummary"]["averageRating"],
            },
            "approved_reviews": [
                {"rating": item["rating"], "body": item["body"], "created_at": item["createdAt"]}
                for item in product.get("approvedReviews") or []
            ],
        }
    except (KeyError, TypeError, AttributeError) as exc:
        raise UpstreamError("GraphQL upstream returned an invalid product payload") from exc


def create_review(slug, rating, body, token):
    query = """
    mutation CreateReview($input: CreateReviewInput!) {
      createReview(input: $input) {
        created status createdAt
        userErrors { field code message }
      }
    }
    """
    payload = _graphql_request(
        query,
        {"input": {"productSlug": slug, "rating": rating, "body": body}},
        token,
    )
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (payload.get("data") or {}).get("createReview")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid review payload")
    errors = result.get("userErrors") or []
    if errors:
        error = errors[0]
        raise UpstreamError(error.get("message", "Review could not be created"), error.get("code"))
    return {
        "created": result["created"],
        "status": result["status"],
        "created_at": result["createdAt"],
    }


def _cart_result(cart, user_errors=None):
    if not isinstance(cart, dict):
        raise UpstreamError("GraphQL upstream returned an invalid cart payload")
    try:
        return {
            "cart_id": cart["cartId"],
            "lines": [
                {
                    "bgg_id": line["bggId"],
                    "name": line["name"],
                    "quantity": line["quantity"],
                    "available_stock": line["inventoryQuantity"],
                    "unit_price": line["unitPrice"],
                    "subtotal": line["subtotal"],
                }
                for line in cart["lines"]
            ],
            "total": cart["subtotal"],
            "warnings": [
                {
                    "field": error.get("field"),
                    "code": error["code"],
                    "message": error["message"],
                }
                for error in (user_errors or [])
            ],
        }
    except (KeyError, TypeError) as exc:
        raise UpstreamError("GraphQL upstream returned an invalid cart payload") from exc


def get_cart(cart_id=None, token=None):
    query = """
    query Cart($cartId: ID) {
      cart(cartId: $cartId) {
        cartId subtotal
        lines { bggId name quantity inventoryQuantity unitPrice subtotal }
      }
    }
    """
    payload = _graphql_request(query, {"cartId": cart_id}, token)
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    cart = (payload.get("data") or {}).get("cart")
    return _cart_result(cart)


def _cart_mutation(field, bgg_id, quantity, cart_id, token):
    if field == "removeFromCart":
        arguments = "$bggId: Int!, $cartId: ID"
        call_arguments = "bggId: $bggId, cartId: $cartId"
    else:
        if quantity is None:
            raise ValueError("quantity is required")
        arguments = "$bggId: Int!, $quantity: Int!, $cartId: ID"
        call_arguments = "bggId: $bggId, quantity: $quantity, cartId: $cartId"
    query = f"""
    mutation CartMutation({arguments}) {{
      {field}({call_arguments}) {{
        cart {{ cartId subtotal lines {{ bggId name quantity inventoryQuantity unitPrice subtotal }} }}
        userErrors {{ field code message }}
      }}
    }}
    """
    variables = {"bggId": bgg_id, "cartId": cart_id}
    if quantity is not None:
        variables["quantity"] = quantity
    payload = _graphql_request(query, variables, token)
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (payload.get("data") or {}).get(field)
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid cart payload")
    return _cart_result(result.get("cart"), result.get("userErrors"))


def add_to_cart(bgg_id, quantity, cart_id=None, token=None):
    return _cart_mutation("addToCart", bgg_id, quantity, cart_id, token)


def update_cart_quantity(bgg_id, quantity, cart_id=None, token=None):
    return _cart_mutation("updateCartQuantity", bgg_id, quantity, cart_id, token)


def remove_from_cart(bgg_id, cart_id=None, token=None):
    return _cart_mutation("removeFromCart", bgg_id, None, cart_id, token)


_WISHLIST_PRODUCT_FIELDS = """
  bggId name releaseYear minPlayers maxPlayers playingTimeMinutes minAge
  weight category price quantity publisher imageUrl
"""


def _map_wishlist_product(product):
    if not isinstance(product, dict):
        raise UpstreamError("GraphQL upstream returned an invalid Wishlist product")
    try:
        return {
            "bgg_id": product["bggId"],
            "name": product["name"],
            "release_year": product["releaseYear"],
            "min_players": product["minPlayers"],
            "max_players": product["maxPlayers"],
            "playing_time_minutes": product["playingTimeMinutes"],
            "min_age": product["minAge"],
            "weight": product["weight"],
            "category": product["category"],
            "price": product["price"],
            "quantity": product["quantity"],
            "publisher": product["publisher"],
            "image_url": product["imageUrl"],
        }
    except (KeyError, TypeError) as exc:
        raise UpstreamError("GraphQL upstream returned an invalid Wishlist product") from exc


def get_wishlist(token):
    query = f"""
    query MyWishlist {{
      myWishlist {{ {_WISHLIST_PRODUCT_FIELDS} }}
    }}
    """
    payload = _graphql_request(query, {}, token, map_wishlist_errors=True)
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    products = (payload.get("data") or {}).get("myWishlist")
    if not isinstance(products, list):
        raise UpstreamError("GraphQL upstream returned an invalid Wishlist payload")
    return [_map_wishlist_product(product) for product in products]


def _wishlist_mutation(field, bgg_id, token):
    query = f"""
    mutation WishlistMutation($bggId: Int!) {{
      {field}(bggId: $bggId) {{ {_WISHLIST_PRODUCT_FIELDS} }}
    }}
    """
    payload = _graphql_request(
        query, {"bggId": bgg_id}, token, map_wishlist_errors=True
    )
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    product = (payload.get("data") or {}).get(field)
    return _map_wishlist_product(product)


def add_to_wishlist(bgg_id, token):
    return _wishlist_mutation("addToWishlist", bgg_id, token)


def remove_from_wishlist(bgg_id, token):
    return _wishlist_mutation("removeFromWishlist", bgg_id, token)


_ORDER_FIELDS = """
  id status total currency shippingMode recipient street city postalCode phone
  paymentStatus paymentStatusDetail createdAt paidAt
  lines { bggId name unitPrice quantity subtotal }
  invoice { number issuedAt total }
"""


def _map_order(order):
    if not isinstance(order, dict):
        raise UpstreamError("GraphQL upstream returned an invalid order payload")
    try:
        invoice = order.get("invoice")
        return {
            "id": order["id"],
            "status": order["status"],
            "total": order["total"],
            "currency": order["currency"],
            "shipping_mode": order["shippingMode"],
            "recipient": order.get("recipient"),
            "street": order.get("street"),
            "city": order.get("city"),
            "postal_code": order.get("postalCode"),
            "phone": order.get("phone"),
            "payment_status": order.get("paymentStatus"),
            "payment_status_detail": order.get("paymentStatusDetail"),
            "created_at": order["createdAt"],
            "paid_at": order.get("paidAt"),
            "lines": [
                {
                    "bgg_id": line["bggId"],
                    "name": line["name"],
                    "unit_price": line["unitPrice"],
                    "quantity": line["quantity"],
                    "subtotal": line["subtotal"],
                }
                for line in order["lines"]
            ],
            "invoice": (
                {"number": invoice["number"], "issued_at": invoice["issuedAt"], "total": invoice["total"]}
                if invoice is not None
                else None
            ),
        }
    except (KeyError, TypeError) as exc:
        raise UpstreamError("GraphQL upstream returned an invalid order payload") from exc


def _raise_order_graphql_errors(payload):
    errors = payload.get("errors") or []
    if any(
        isinstance(error, dict)
        and (
            (error.get("extensions") or {}).get("code") == "UNAUTHENTICATED"
            or error.get("message") == "Authentication is required."
        )
        for error in errors
    ):
        raise UpstreamError("Authentication is required.", "UNAUTHENTICATED")
    if errors:
        raise UpstreamError("GraphQL upstream returned errors")


def _order_payload(payload, field):
    _raise_order_graphql_errors(payload)
    result = (payload.get("data") or {}).get(field)
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid order payload")
    errors = result.get("userErrors") or []
    if not isinstance(errors, list):
        raise UpstreamError("GraphQL upstream returned an invalid order error payload")
    if errors:
        error = errors[0]
        if not isinstance(error, dict):
            raise UpstreamError("GraphQL upstream returned an invalid order error payload")
        raise UpstreamError(
            error.get("message", "Order operation failed"),
            error.get("code", "INVALID"),
            error.get("field"),
            user_error=True,
        )
    order = result.get("order")
    if order is None:
        raise UpstreamError("Order not found", "ORDER_NOT_FOUND")
    return {"order": _map_order(order), "init_point": result.get("initPoint")}


def checkout(shipping_mode, address, token, coupon_code=None, checkout_key=None):
    query = f"""
    mutation Checkout($address: ShippingAddressInput, $shippingMode: ShippingMode!, $couponCode: String, $checkoutKey: String) {{
      checkout(address: $address, shippingMode: $shippingMode, couponCode: $couponCode, checkoutKey: $checkoutKey) {{
        order {{ {_ORDER_FIELDS} }} initPoint userErrors {{ field code message }}
      }}
    }}
    """
    core_address = None if address is None else {
        "recipient": address.get("recipient"),
        "street": address.get("street"),
        "city": address.get("city"),
        "postalCode": address.get("postal_code"),
        "phone": address.get("phone"),
    }
    payload = _graphql_request(query, {
        "address": core_address,
        "shippingMode": shipping_mode.upper(),
        "couponCode": coupon_code,
        "checkoutKey": checkout_key,
    }, token)
    try:
        return _order_payload(payload, "checkout")
    except UpstreamError as exc:
        status_by_code = {
            "COUPON_NOT_FOUND": 404,
            "COUPON_INACTIVE": 422,
            "COUPON_NOT_YET_VALID": 422,
            "COUPON_EXPIRED": 422,
            "COUPON_EXHAUSTED": 422,
            "DISCOUNT_LIMIT_EXCEEDED": 422,
            "IDEMPOTENCY_CONFLICT": 409,
        }
        status = status_by_code.get(exc.code)
        if status is None:
            raise
        safe_messages = {
            "COUPON_NOT_FOUND": "Coupon not found.",
            "COUPON_INACTIVE": "Coupon is not eligible for checkout.",
            "COUPON_NOT_YET_VALID": "Coupon is not eligible for checkout.",
            "COUPON_EXPIRED": "Coupon is not eligible for checkout.",
            "COUPON_EXHAUSTED": "Coupon is not eligible for checkout.",
            "DISCOUNT_LIMIT_EXCEEDED": "Coupon is not eligible for checkout.",
            "IDEMPOTENCY_CONFLICT": "X-Op-Key was already used for a different checkout.",
        }
        return (
            {"errors": [{"code": exc.code, "message": safe_messages[exc.code]}]},
            status,
        )


def preview_coupon(code, token):
    query = """
    query PreviewCoupon($code: String!) {
      previewCoupon(code: $code) {
        valid couponCode discountAmount newTotal reason
      }
    }
    """
    payload = _graphql_request(query, {"code": code}, token)
    if not isinstance(payload, dict):
        raise UpstreamError("GraphQL upstream returned an invalid coupon preview")
    errors = payload.get("errors") or []
    if errors:
        codes = [
            error.get("extensions", {}).get("code")
            for error in errors if isinstance(error, dict)
        ]
        if "UNAUTHENTICATED" in codes:
            raise UpstreamError("Authentication is required.", "UNAUTHENTICATED")
        if "NOT_FOUND" in codes:
            raise UpstreamError("Coupon not found.", "COUPON_NOT_FOUND")
        raise UpstreamError("GraphQL upstream request failed")
    result = (payload.get("data") or {}).get("previewCoupon")
    if (
        not isinstance(result, dict)
        or type(result.get("valid")) is not bool
        or result.get("couponCode") != code
        or (
            result.get("reason") is not None
            and result["reason"] not in {
                "INACTIVE", "NOT_YET_VALID", "EXPIRED", "EXHAUSTED",
                "DISCOUNT_LIMIT_EXCEEDED", "EMPTY_CART",
            }
        )
    ):
        raise UpstreamError("GraphQL upstream returned an invalid coupon preview")
    for field in ("discountAmount", "newTotal"):
        value = result.get(field)
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or value < 0
        ):
            raise UpstreamError("GraphQL upstream returned an invalid coupon preview")
    return {
        "valid": result["valid"],
        "coupon_code": result["couponCode"],
        "discount_amount": result["discountAmount"],
        "new_total": result["newTotal"],
        "reason": result.get("reason"),
    }


def retry_payment(order_id, token):
    query = f"""
    mutation RetryPayment($orderId: ID!) {{
      retryPayment(orderId: $orderId) {{
        order {{ {_ORDER_FIELDS} }} initPoint userErrors {{ field code message }}
      }}
    }}
    """
    return _order_payload(_graphql_request(query, {"orderId": order_id}, token), "retryPayment")


def confirm_payment(order_id, payment_id, token):
    query = f"""
    mutation ConfirmPayment($orderId: ID!, $paymentId: ID!) {{
      confirmPayment(orderId: $orderId, paymentId: $paymentId) {{
        order {{ {_ORDER_FIELDS} }} userErrors {{ field code message }}
      }}
    }}
    """
    result = _order_payload(
        _graphql_request(query, {"orderId": order_id, "paymentId": payment_id}, token),
        "confirmPayment",
    )
    return {"order": result["order"]}


def get_orders(token):
    query = f"""
    query MyOrders {{ myOrders {{ {_ORDER_FIELDS} }} }}
    """
    payload = _graphql_request(query, {}, token)
    _raise_order_graphql_errors(payload)
    orders = (payload.get("data") or {}).get("myOrders")
    if not isinstance(orders, list):
        raise UpstreamError("GraphQL upstream returned an invalid orders payload")
    return [_map_order(order) for order in orders]


def get_order(order_id, token):
    query = f"""
    query MyOrder($id: ID!) {{ myOrder(id: $id) {{ {_ORDER_FIELDS} }} }}
    """
    payload = _graphql_request(query, {"id": order_id}, token)
    _raise_order_graphql_errors(payload)
    order = (payload.get("data") or {}).get("myOrder")
    if order is None:
        raise UpstreamError("Order not found", "ORDER_NOT_FOUND")
    return _map_order(order)


def get_invoice(order_id, token):
    try:
        identifier = str(uuid.UUID(order_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("order_id must be a UUID") from exc
    auth_payload = _graphql_request("query InvoiceAuthCheck { myOrders { id } }", {}, token)
    _raise_order_graphql_errors(auth_payload)
    if not isinstance((auth_payload.get("data") or {}).get("myOrders"), list):
        raise UpstreamError("GraphQL upstream returned an invalid orders payload")
    graphql_url = os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL)
    parsed = urlsplit(graphql_url)
    base_path = parsed.path.rstrip("/").rsplit("/graphql", 1)[0]
    invoice_url = urlunsplit((parsed.scheme, parsed.netloc, base_path + "/invoices/" + identifier + "/", "", ""))
    try:
        response = requests.get(
            invoice_url,
            headers={"Authorization": token},
            timeout=30,
            stream=True,
        )
        if response.status_code != 404:
            response.raise_for_status()
        return response
    except requests.RequestException:
        raise UpstreamError("Invoice upstream request failed") from None


def check_admin(token, require_active=False):
    """Return admin status, or None when Core reports no authenticated user."""
    active_field = "isActive" if require_active else ""
    query = f"""
    query WhoAmI {{
      me {{ id email {active_field} isStaff isSuperuser }}
    }}
    """
    if not token or not isinstance(token, str) or not token.strip():
        return None
    token = token.strip()
    payload = _graphql_request(query, {}, token)
    if not isinstance(payload, dict):
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    if payload.get("errors"):
        error = next(
            (item for item in payload["errors"] if isinstance(item, dict)),
            {},
        )
        extensions = error.get("extensions")
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if require_active and code == "UNAUTHENTICATED":
            return None
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    data = payload.get("data")
    if not isinstance(data, dict) or "me" not in data:
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    me = data["me"]
    if me is None:
        return None
    if (not isinstance(me, dict)
            or any(not isinstance(me.get(field), str) or not me[field] for field in ("id", "email"))
            or any(type(me.get(field)) is not bool for field in ("isStaff", "isSuperuser"))):
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    if require_active:
        if type(me.get("isActive")) is not bool:
            raise UpstreamError("GraphQL upstream returned an invalid identity")
        if not me["isActive"]:
            return False
    return me["isStaff"] or me["isSuperuser"]


def get_current_user_capabilities(token):
    query = """
    query CurrentUserCapabilities {
      me { isActive isStaff isSuperuser }
    }
    """
    payload = _graphql_request(query, {}, token)
    if not isinstance(payload, dict):
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    if errors:
        if any(
            isinstance(error, dict)
            and isinstance(error.get("extensions"), dict)
            and error["extensions"].get("code") == "UNAUTHENTICATED"
            for error in errors
        ):
            raise UpstreamError("Authentication is required.", "UNAUTHENTICATED", user_error=True)
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    data = payload.get("data")
    if not isinstance(data, dict) or "me" not in data:
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    me = data["me"]
    if me is None:
        raise UpstreamError("Authentication is required.", "UNAUTHENTICATED", user_error=True)
    if not isinstance(me, dict) or any(
        type(me.get(field)) is not bool
        for field in ("isActive", "isStaff", "isSuperuser")
    ):
        raise UpstreamError("GraphQL upstream returned an invalid identity")
    if not me["isActive"]:
        raise UpstreamError("Authentication is required.", "UNAUTHENTICATED", user_error=True)
    return {
        "is_staff": me["isStaff"],
        "is_superuser": me["isSuperuser"],
    }


def _review_moderation_error(payload):
    for error in payload.get("errors") or []:
        extensions = error.get("extensions") if isinstance(error, dict) else None
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if code in (
            "UNAUTHENTICATED",
            "FORBIDDEN",
            "REVIEW_NOT_FOUND",
            "INVALID_TRANSITION",
        ):
            return UpstreamError(
                "Review moderation request rejected",
                code,
                user_error=True,
            )
    return UpstreamError("GraphQL upstream returned errors")


def _moderation_user_error(errors):
    for error in errors:
        code = error.get("code") if isinstance(error, dict) else None
        if code in (
            "UNAUTHENTICATED",
            "FORBIDDEN",
            "REVIEW_NOT_FOUND",
            "INVALID_TRANSITION",
        ):
            return UpstreamError(
                "Review moderation request rejected",
                code,
                user_error=True,
            )
    return UpstreamError("GraphQL upstream returned errors")


def _moderation_id(value):
    if isinstance(value, bool):
        raise UpstreamError("GraphQL upstream returned an invalid review")
    try:
        identifier = int(value)
    except (TypeError, ValueError):
        raise UpstreamError("GraphQL upstream returned an invalid review") from None
    if not 1 <= identifier <= 2147483647:
        raise UpstreamError("GraphQL upstream returned an invalid review")
    return identifier


def list_admin_reviews(filters, token):
    query = """
    query AdminReviews($status: ReviewModerationStatus, $page: Int!, $pageSize: Int!) {
      adminReviews(status: $status, page: $page, pageSize: $pageSize) {
        items { id gameBggId gameName rating body createdAt status }
        page pageSize total totalPages
      }
    }
    """
    payload = _graphql_request(query, filters, token)
    if not isinstance(payload, dict):
        raise UpstreamError("GraphQL upstream returned an invalid response")
    if payload.get("errors"):
        raise _review_moderation_error(payload)
    page = (payload.get("data") or {}).get("adminReviews")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise UpstreamError("GraphQL upstream returned an invalid review page")
    items = []
    try:
        for item in page["items"]:
            if not isinstance(item, dict):
                raise TypeError
            game_bgg_id = item["gameBggId"]
            rating = item["rating"]
            if (type(game_bgg_id) is not int or game_bgg_id < 1
                    or type(rating) is not int or not 1 <= rating <= 5
                    or not isinstance(item["gameName"], str)
                    or not isinstance(item["body"], str)
                    or not 1 <= len(item["body"]) <= 2000
                    or not isinstance(item["createdAt"], str)
                    or item["status"] not in ("PENDING", "ACCEPTED", "REJECTED")):
                raise TypeError
            items.append({
                "review_id": _moderation_id(item["id"]),
                "game_bgg_id": game_bgg_id,
                "game_name": item["gameName"],
                "rating": rating,
                "body": item["body"],
                "created_at": item["createdAt"],
                "status": item["status"],
            })
        result = {
            "items": items,
            "page": page["page"],
            "page_size": page["pageSize"],
            "total": page["total"],
            "total_pages": page["totalPages"],
        }
        if any(type(result[key]) is not int for key in ("page", "page_size", "total", "total_pages")):
            raise TypeError
        if result["page"] < 1 or not 1 <= result["page_size"] <= 100:
            raise TypeError
        if result["total"] < 0 or result["total_pages"] < 0:
            raise TypeError
    except (KeyError, TypeError, ValueError):
        raise UpstreamError("GraphQL upstream returned an invalid review page") from None
    return result


def moderate_admin_review(review_id, action, token):
    query = """
    mutation ModerateReview($reviewId: ID!, $action: ReviewModerationAction!) {
      moderateReview(reviewId: $reviewId, action: $action) {
        success
        review { id status deleted publiclyVisible }
        userErrors { field code message }
      }
    }
    """
    payload = _graphql_request(
        query,
        {"reviewId": str(review_id), "action": action},
        token,
    )
    if not isinstance(payload, dict):
        raise UpstreamError("GraphQL upstream returned an invalid response")
    if payload.get("errors"):
        raise _review_moderation_error(payload)
    result = (payload.get("data") or {}).get("moderateReview")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid moderation result")
    errors = result.get("userErrors")
    if not isinstance(errors, list):
        raise UpstreamError("GraphQL upstream returned an invalid moderation result")
    if errors:
        raise _moderation_user_error(errors)
    review = result.get("review")
    if result.get("success") is not True or not isinstance(review, dict):
        raise UpstreamError("GraphQL upstream returned an invalid moderation result")
    status = review.get("status")
    if (status not in ("PENDING", "ACCEPTED", "REJECTED")
            or type(review.get("deleted")) is not bool
            or type(review.get("publiclyVisible")) is not bool):
        raise UpstreamError("GraphQL upstream returned an invalid moderation result")
    return {
        "review_id": _moderation_id(review.get("id")),
        "status": status,
        "deleted": review["deleted"],
        "publicly_visible": review["publiclyVisible"],
    }


def list_available_coupons():
    query = """
    query AvailableCoupons {
      availableCoupons { code startsAt endsAt }
    }
    """
    payload = _graphql_request(query, {})
    if not isinstance(payload, dict) or payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    data = payload.get("data")
    coupons = data.get("availableCoupons") if isinstance(data, dict) else None
    if not isinstance(coupons, list):
        raise UpstreamError("GraphQL upstream returned an invalid coupon list")
    result = []
    for coupon in coupons:
        if not isinstance(coupon, dict) or not isinstance(coupon.get("code"), str) or not coupon["code"].strip():
            raise UpstreamError("GraphQL upstream returned an invalid coupon")
        dates = []
        for field in ("startsAt", "endsAt"):
            value = coupon.get(field)
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
            except ValueError:
                parsed = None
            if parsed is None or parsed.utcoffset() is None:
                raise UpstreamError("GraphQL upstream returned an invalid coupon date")
            dates.append(value)
        result.append({"code": coupon["code"], "starts_at": dates[0], "ends_at": dates[1]})
    return result


def list_promotions():
    query = """
    query ListPromotions {
            promotions { id name discountPercent: discountPct active productBggId }
    }
    """
    payload = _graphql_request(query, {}, None)
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    promotions = (payload.get("data") or {}).get("promotions")
    if not isinstance(promotions, list):
        raise UpstreamError("GraphQL upstream returned an invalid promotions payload")
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "discount_percent": p.get("discountPercent"),
            "active": bool(p.get("active")),
            "product_bgg_id": p.get("productBggId"),
        }
        for p in promotions
    ]


def create_promotion(payload, token=None, op_key=None):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    query = """
    mutation CreatePromotion($input: CreatePromotionInput!) {
      createPromotion(input: $input) {
        promotion { id name }
        userErrors { field code message }
      }
    }
    """
    # Map incoming payload keys (snake_case) to upstream GraphQL input (camelCase)
    def _to_camel(s: str) -> str:
        parts = s.split('_')
        return parts[0] + ''.join(p.title() for p in parts[1:]) if len(parts) > 1 else s

    mapped = {}
    # Explicit mappings for known fields
    if 'name' in payload:
        mapped['name'] = payload['name']
    if 'discount_percent' in payload:
        # upstream expects camelCase 'discountPercent'
        mapped['discountPercent'] = payload['discount_percent']
    if 'active' in payload:
        mapped['active'] = payload['active']
    # copy any other fields converting snake_case -> camelCase
    for k, v in payload.items():
        if k in ('name', 'discount_percent', 'active'):
            continue
        mapped[_to_camel(k)] = v

    variables = {"input": mapped}
    resp = _graphql_request(query, variables, token, op_key=op_key)
    if resp.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (resp.get("data") or {}).get("createPromotion")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid createPromotion payload")
    errors = result.get("userErrors") or []
    if errors:
        err = errors[0]
        raise UpstreamError(err.get("message", "Create promotion failed"), err.get("code"), err.get("field"), user_error=True)
    promo = result.get("promotion")
    return {"id": promo.get("id"), "name": promo.get("name")}


def update_promotion(promotion_id, payload, token=None, op_key=None):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    query = """
    mutation UpdatePromotion($id: ID!, $input: UpdatePromotionInput!) {
      updatePromotion(id: $id, input: $input) {
        promotion { id name }
        userErrors { field code message }
      }
    }
    """
    variables = {"id": promotion_id, "input": {
        {"discount_percent": "discountPercent", "product_bgg_id": "productBggId"}.get(key, key): value
        for key, value in payload.items()
    }}
    resp = _graphql_request(query, variables, token, op_key=op_key)
    if resp.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (resp.get("data") or {}).get("updatePromotion")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid updatePromotion payload")
    errors = result.get("userErrors") or []
    if errors:
        err = errors[0]
        raise UpstreamError(err.get("message", "Update promotion failed"), err.get("code"), err.get("field"), user_error=True)
    promo = result.get("promotion")
    return {"id": promo.get("id"), "name": promo.get("name")}


_ADMIN_COUPON_FIELDS = """
    id code discountPercent remaining active startsAt endsAt createdAt
"""


def _coupon_datetime(value, field, nullable=False):
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        raise UpstreamError("GraphQL upstream returned an invalid coupon")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise UpstreamError("GraphQL upstream returned an invalid coupon") from None
    if parsed.utcoffset() is None:
        raise UpstreamError("GraphQL upstream returned an invalid coupon")
    return value


def _map_admin_coupon(coupon):
    if not isinstance(coupon, dict):
        raise UpstreamError("GraphQL upstream returned an invalid coupon")
    identifier = coupon.get("id")
    discount = coupon.get("discountPercent")
    remaining = coupon.get("remaining")
    active = coupon.get("active")
    if (
        type(identifier) is not int or identifier < 1
        or not isinstance(coupon.get("code"), str) or not coupon["code"]
        or isinstance(discount, bool) or not isinstance(discount, (int, float))
        or not 0 <= discount <= 50
        or type(remaining) is not int or remaining < 0
        or type(active) is not bool
    ):
        raise UpstreamError("GraphQL upstream returned an invalid coupon")
    starts_at = _coupon_datetime(coupon.get("startsAt"), "startsAt", nullable=True)
    ends_at = _coupon_datetime(coupon.get("endsAt"), "endsAt", nullable=True)
    created_at = _coupon_datetime(coupon.get("createdAt"), "createdAt")
    if starts_at and ends_at:
        start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        if start >= end:
            raise UpstreamError("GraphQL upstream returned an invalid coupon")
    return {
        "id": identifier,
        "code": coupon["code"],
        "discount_percent": discount,
        "remaining": remaining,
        "active": active,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "created_at": created_at,
    }


def _admin_coupon_user_errors(payload, operation):
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (payload.get("data") or {}).get(operation)
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid coupon payload")
    errors = result.get("userErrors") or []
    if errors:
        error = errors[0]
        code = error.get("code")
        message = error.get("message")
        field = error.get("field")
        if (
            not isinstance(code, str) or not isinstance(message, str)
            or (field is not None and not isinstance(field, list))
        ):
            raise UpstreamError("GraphQL upstream returned an invalid coupon error")
        raise UpstreamError(message, code, field, user_error=True)
    return result.get("coupon")


_AUDIT_SENSITIVE_KEY = re.compile(
    r"password|passwd|secret|token|credential|authorization|api[_-]?key|card|cvv|cvc|payment|iban",
    re.IGNORECASE,
)
_AUDIT_FIELD_NAMES = {
    "entityType": "entity_type", "entityId": "entity_id", "actorId": "actor_id",
    "action": "action", "createdFrom": "created_from", "createdTo": "created_to",
    "cursor": "cursor", "limit": "limit",
}


def _audit_redact(value, depth=0):
    if depth > 12:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _AUDIT_SENSITIVE_KEY.search(str(key)) else _audit_redact(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_audit_redact(item, depth + 1) for item in value]
    return value


def _audit_changes(value):
    if value is None:
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None
    return _audit_redact(parsed) if isinstance(parsed, (dict, list)) else None


def _audit_graphql_error(payload):
    for error in payload.get("errors") or []:
        extensions = error.get("extensions") if isinstance(error, dict) else None
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if code in ("UNAUTHENTICATED", "FORBIDDEN"):
            return UpstreamError("Audit request rejected", code, user_error=True)
        if code == "INVALID":
            field = _AUDIT_FIELD_NAMES.get(extensions.get("field"), extensions.get("field"))
            field = field if field in _AUDIT_FIELD_NAMES.values() else None
            return UpstreamError("Audit request is invalid", "INVALID", [field] if field else None, user_error=True)
        break
    return UpstreamError("GraphQL upstream returned errors")


def list_admin_audit(filters, token=None, op_key=None):
    query = """
    query AdminAudit($entityType: String, $entityId: String, $actorId: String, $action: String,
                     $createdFrom: String, $createdTo: String, $cursor: String, $limit: Int) {
      adminAuditLogs(entityType: $entityType, entityId: $entityId, actorId: $actorId, action: $action,
                     createdFrom: $createdFrom, createdTo: $createdTo, cursor: $cursor, limit: $limit) {
        records { id actorId action entityType entityId createdAt before after }
        nextCursor
      }
    }
    """
    camel = {value: key for key, value in _AUDIT_FIELD_NAMES.items()}
    variables = {camel[key]: value for key, value in filters.items() if key in camel}
    payload = _graphql_request(query, variables, token)
    if payload.get("errors"):
        raise _audit_graphql_error(payload)
    page = (payload.get("data") or {}).get("adminAuditLogs")
    if not isinstance(page, dict) or not isinstance(page.get("records"), list):
        raise UpstreamError("GraphQL upstream returned an invalid audit page")
    items = []
    for record in page["records"]:
        if not isinstance(record, dict):
            raise UpstreamError("GraphQL upstream returned an invalid audit record")
        items.append({
            "id": record.get("id"),
            "actor_id": record.get("actorId"),
            "action": record.get("action"),
            "entity_type": record.get("entityType"),
            "entity_id": record.get("entityId"),
            "created_at": record.get("createdAt"),
            "changes": {
                "before": _audit_changes(record.get("before")),
                "after": _audit_changes(record.get("after")),
            },
        })
    return {"items": items, "next_cursor": page.get("nextCursor")}


def _admin_sales_graphql_error(payload):
    for error in payload.get("errors") or []:
        extensions = error.get("extensions") if isinstance(error, dict) else None
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if code in ("UNAUTHENTICATED", "FORBIDDEN"):
            return UpstreamError("Sales metrics request rejected", code, user_error=True)
        if code == "INVALID":
            field = extensions.get("field")
            field_names = {
                "from": "from",
                "to": "to",
                "categories": "category",
                "productIds": "product_id",
            }
            field = field_names.get(field) if isinstance(field, str) else None
            return UpstreamError(
                "Sales metrics request is invalid",
                "INVALID",
                [field] if field else None,
                user_error=True,
            )
        break
    return UpstreamError("GraphQL upstream returned errors")


def get_admin_sales_metrics(filters, token=None, op_key=None):
    query = """
    query AdminSalesMetrics($from: String, $to: String, $categories: [String!], $productIds: [Int!]) {
      adminSalesMetrics(from: $from, to: $to, categories: $categories, productIds: $productIds) {
        revenueTotal
        ordersCount
        topProducts { bggId name units revenue }
        ordersByDispatchStatus { status count }
        ordersByPaymentStatus { status count }
        revenueByDay { date revenue }
      }
    }
    """
    variables = {
        "from": filters.get("from"),
        "to": filters.get("to"),
        "categories": filters.get("categories"),
        "productIds": filters.get("product_ids"),
    }
    payload = _graphql_request(query, variables, token, op_key=op_key)
    if payload.get("errors"):
        raise _admin_sales_graphql_error(payload)
    metrics = (payload.get("data") or {}).get("adminSalesMetrics")
    if not isinstance(metrics, dict):
        raise UpstreamError("GraphQL upstream returned invalid sales metrics")
    try:
        return {
            "revenue_total": metrics["revenueTotal"],
            "orders_count": metrics["ordersCount"],
            "top_products": [
                {
                    "bgg_id": item["bggId"],
                    "name": item["name"],
                    "units": item["units"],
                    "revenue": item["revenue"],
                }
                for item in metrics["topProducts"]
            ],
            "orders_by_dispatch_status": [
                {"status": item["status"], "count": item["count"]}
                for item in metrics["ordersByDispatchStatus"]
            ],
            "orders_by_payment_status": [
                {"status": item["status"], "count": item["count"]}
                for item in metrics["ordersByPaymentStatus"]
            ],
            "revenue_by_day": [
                {"date": item["date"], "revenue": item["revenue"]}
                for item in metrics["revenueByDay"]
            ],
        }
    except (KeyError, TypeError):
        raise UpstreamError("GraphQL upstream returned invalid sales metrics") from None


def get_admin_sales_categories(token=None, op_key=None):
    query = """
    query AdminSalesCategories {
      adminSalesCategories
    }
    """
    payload = _graphql_request(query, {}, token, op_key=op_key)
    if payload.get("errors"):
        raise _admin_sales_graphql_error(payload)
    categories = (payload.get("data") or {}).get("adminSalesCategories")
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        raise UpstreamError("GraphQL upstream returned invalid sales categories")
    return categories


def list_admin_coupons(token=None, op_key=None):
    query = f"""
    query AdminCoupons {{
      adminCoupons {{ {_ADMIN_COUPON_FIELDS} }}
    }}
    """
    payload = _graphql_request(query, {}, token)
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    coupons = (payload.get("data") or {}).get("adminCoupons")
    if not isinstance(coupons, list):
        raise UpstreamError("GraphQL upstream returned an invalid coupon list")
    return [_map_admin_coupon(coupon) for coupon in coupons]


def create_admin_coupon(payload, token=None, op_key=None):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    query = f"""
    mutation CreateAdminCoupon($input: AdminCreateCouponInput!) {{
      createAdminCoupon(input: $input) {{
        coupon {{ {_ADMIN_COUPON_FIELDS} }}
        userErrors {{ field code message }}
      }}
    }}
    """
    mapped = {
        {
            "discount_percent": "discountPercent",
            "starts_at": "startsAt",
            "ends_at": "endsAt",
        }.get(key, key): value
        for key, value in payload.items()
    }
    result = _admin_coupon_user_errors(
        _graphql_request(query, {"input": mapped}, token, op_key=op_key),
        "createAdminCoupon",
    )
    return _map_admin_coupon(result)


def update_admin_coupon(coupon_id, payload, token=None, op_key=None):
    if type(coupon_id) is not int or not 1 <= coupon_id <= 2147483647:
        raise ValueError("coupon_id must be a positive integer")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    query = f"""
    mutation UpdateAdminCoupon($id: Int!, $input: AdminUpdateCouponInput!) {{
      updateAdminCoupon(id: $id, input: $input) {{
        coupon {{ {_ADMIN_COUPON_FIELDS} }}
        userErrors {{ field code message }}
      }}
    }}
    """
    mapped = {
        {
            "discount_percent": "discountPercent",
            "starts_at": "startsAt",
            "ends_at": "endsAt",
        }.get(key, key): value
        for key, value in payload.items()
    }
    result = _admin_coupon_user_errors(
        _graphql_request(query, {"id": coupon_id, "input": mapped}, token, op_key=op_key),
        "updateAdminCoupon",
    )
    return _map_admin_coupon(result)


# Admin mutations and management helpers
def create_product(payload, token=None, op_key=None):
    # Basic validation
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    # Normalize payload to GraphQL contract: expect camelCase only.
    # Map legacy/incorrect client fields to the canonical contract names.
    if isinstance(payload, dict):
        # priceAmount -> price (frontend sent priceAmount previously)
        if "priceAmount" in payload and "price" not in payload:
            try:
                payload["price"] = payload.pop("priceAmount")
            except Exception:
                # fallback: ignore if conversion fails
                pass
        # Normalize common snake_case keys to camelCase per GraphQL contract
        snake_to_camel = {
            'bgg_id': 'bggId',
            'image_file_name': 'imageFileName',
            'image_url': 'imageUrl',
            'release_year': 'releaseYear',
            'min_players': 'minPlayers',
            'max_players': 'maxPlayers',
            'playing_time_minutes': 'playingTimeMinutes',
            'min_age': 'minAge',
            'max_age': 'maxAge',
            'price_amount': 'price',
        }
        for k in list(payload.keys()):
            if k in snake_to_camel:
                camel = snake_to_camel[k]
                # prefer existing camelCase value if present
                if camel not in payload or payload.get(camel) in (None, ''):
                    try:
                        payload[camel] = payload.pop(k)
                    except Exception:
                        try:
                            # best-effort: delete the snake_case key if it collides
                            del payload[k]
                        except Exception:
                            pass
    name = payload.get("name")
    if not name:
        raise ValueError("name is required")
    query = """
    mutation CreateProduct($input: CreateProductInput!) {
      createProduct(input: $input) {
        product { bggId name }
        userErrors { field code message }
      }
    }
    """
    variables = {"input": payload}
    payload_resp = _graphql_request(query, variables, token, op_key=op_key)
    if payload_resp.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (payload_resp.get("data") or {}).get("createProduct")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid createProduct payload")
    errors = result.get("userErrors") or []
    if errors:
        err = errors[0]
        raise UpstreamError(err.get("message", "Create product failed"), err.get("code"), err.get("field"), user_error=True)
    product = result.get("product")
    # Persist a compact record of created product for immediate BFF-level
    # lookup to tolerate upstream eventual-consistency in listing/indexing.
    try:
        import json, datetime
        rec = {
            'ts': datetime.datetime.utcnow().isoformat() + 'Z',
            'bgg_id': product.get('bggId'),
            'name': product.get('name'),
        }
        with open('/tmp/bff-created-products.log', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"bgg_id": product.get("bggId"), "name": product.get("name")}


def update_product(product_id, payload, token=None, op_key=None):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    # Normalize payload to GraphQL contract: expect camelCase only.
    # Map legacy/incorrect client fields to the canonical contract names.
    try:
        # priceAmount -> price (frontend historically sent priceAmount)
        if "priceAmount" in payload and "price" not in payload:
            try:
                payload["price"] = payload.pop("priceAmount")
            except Exception:
                pass
        # Normalize common snake_case keys to camelCase per GraphQL contract
        snake_to_camel = {
            'bgg_id': 'bggId',
            'image_file_name': 'imageFileName',
            'image_url': 'imageUrl',
            'release_year': 'releaseYear',
            'min_players': 'minPlayers',
            'max_players': 'maxPlayers',
            'playing_time_minutes': 'playingTimeMinutes',
            'min_age': 'minAge',
            'max_age': 'maxAge',
            'price_amount': 'price',
        }
        for k in list(payload.keys()):
            if k in snake_to_camel:
                camel = snake_to_camel[k]
                if camel not in payload or payload.get(camel) in (None, ''):
                    try:
                        payload[camel] = payload.pop(k)
                    except Exception:
                        try:
                            del payload[k]
                        except Exception:
                            pass
    except Exception:
        # best-effort normalization; never fail the request due to normalization errors
        pass

    # Ensure we do not send identifier fields inside the `input` GraphQL object.
    # The Core mutation expects the `id` argument separately, not `bggId` inside input.
    try:
        if 'bggId' in payload:
            try:
                payload.pop('bggId')
            except Exception:
                pass
        if 'bgg_id' in payload:
            try:
                payload.pop('bgg_id')
            except Exception:
                pass
    except Exception:
        pass

    query = """
    mutation UpdateProduct($id: ID!, $input: UpdateProductInput!) {
      updateProduct(id: $id, input: $input) {
        product { bggId name }
        userErrors { field code message }
      }
    }
    """
    variables = {"id": product_id, "input": payload}
    payload_resp = _graphql_request(query, variables, token, op_key=op_key)
    if payload_resp.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (payload_resp.get("data") or {}).get("updateProduct")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid updateProduct payload")
    errors = result.get("userErrors") or []
    if errors:
        err = errors[0]
        raise UpstreamError(err.get("message", "Update product failed"), err.get("code"), err.get("field"), user_error=True)
    product = result.get("product")
    return {"bgg_id": product.get("bggId"), "name": product.get("name")}


def get_stock_movement_status(movement_id, token=None):
    query = """
    query StockMovementStatus($movementId: ID!) {
      adminStockMovementStatus(movementId: $movementId) {
        movementId status userErrors { code }
      }
    }
    """
    payload = _graphql_request(query, {"movementId": movement_id}, token)
    if not isinstance(payload, dict) or payload.get("errors"):
        raise UpstreamError("Stock status request failed")
    data = payload.get("data")
    result = data.get("adminStockMovementStatus") if isinstance(data, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("userErrors"), list):
        raise UpstreamError("Stock status request failed")
    try:
        if str(uuid.UUID(result["movementId"])) != movement_id:
            raise ValueError("Movement identifier mismatch")
    except (KeyError, ValueError, TypeError, AttributeError):
        raise UpstreamError("Stock status request failed") from None
    errors = result["userErrors"]
    if errors:
        if not isinstance(errors[0], dict) or not isinstance(errors[0].get("code"), str) or result.get("status") is not None:
            raise UpstreamError("Stock status request failed")
        raise UpstreamError("Stock status request failed", errors[0]["code"], user_error=True)
    if result.get("status") not in ("IN_PROGRESS", "APPLIED", "REJECTED"):
        raise UpstreamError("Stock status request failed")
    return {"movement_id": movement_id, "status": result["status"]}


def adjust_product_stock(product_id, movement_id, direction, quantity, token=None):
    query = """
    mutation AdjustProductStock($productId: ID!, $movementId: ID!, $direction: StockMovementDirection!, $quantity: Int!) {
      adjustProductStock(productId: $productId, movementId: $movementId, direction: $direction, quantity: $quantity) {
        movementId status requestedQuantity appliedQuantity quantityBefore quantityAfter errors { code }
      }
    }
    """
    variables = {"productId": product_id, "movementId": movement_id, "direction": direction, "quantity": quantity}
    payload = _graphql_request(query, variables, token)
    if not isinstance(payload, dict) or payload.get("errors"):
        raise UpstreamError("Stock movement request failed")
    data = payload.get("data")
    result = data.get("adjustProductStock") if isinstance(data, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("errors"), list):
        raise UpstreamError("Stock movement request failed")
    try:
        if str(uuid.UUID(result["movementId"])) != movement_id:
            raise ValueError("Movement identifier mismatch")
    except (KeyError, ValueError, TypeError, AttributeError):
        raise UpstreamError("Stock movement request failed") from None
    errors = result["errors"]
    if errors:
        if not isinstance(errors[0], dict) or not isinstance(errors[0].get("code"), str) or result.get("status") is not None:
            raise UpstreamError("Stock movement request failed")
        raise UpstreamError("Stock movement request failed", errors[0]["code"], user_error=True)
    if result.get("status") == "IN_PROGRESS":
        if any(result.get(field) is not None for field in ("requestedQuantity", "appliedQuantity", "quantityBefore", "quantityAfter")):
            raise UpstreamError("Stock movement request failed")
        return {"movement_id": movement_id, "status": "IN_PROGRESS"}
    values = [result.get(field) for field in ("requestedQuantity", "appliedQuantity", "quantityBefore", "quantityAfter")]
    if result.get("status") != "APPLIED" or any(type(value) is not int or value < 0 for value in values):
        raise UpstreamError("Stock movement request failed")
    requested, applied, before, after = values
    expected_applied = quantity if direction == "IN" else min(before, quantity)
    expected_after = before + applied if direction == "IN" else before - applied
    if requested != quantity or applied != expected_applied or after != expected_after or after > 2147483647:
        raise UpstreamError("Stock movement request failed")
    response = {"movement_id": movement_id, "status": "APPLIED", "requested_quantity": requested,
                "applied_quantity": applied, "quantity_before": before, "quantity_after": after}
    if direction == "OUT" and applied < requested:
        response["warning"] = "Requested quantity exceeded available stock; stock is now zero."
    return response


def apply_coupon_preview(code, input_payload):
    """Preview applying a coupon to a cart or guest session.

    Returns a dict with keys: valid, discountAmount, newTotal.
    Raises UpstreamError with user_error=True when GraphQL reports userErrors.
    """
    query = """
    mutation ApplyCouponPreview($code: String!, $input: ApplyCouponInput) {
      applyCouponPreview(code: $code, input: $input) {
        valid
        discountAmount
        newTotal
        userErrors { field code message }
      }
    }
    """
    variables = {"code": code, "input": input_payload}
    payload = _graphql_request(query, variables)
    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (payload.get("data") or {}).get("applyCouponPreview")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid applyCouponPreview payload")
    user_errors = result.get("userErrors") or []
    if user_errors:
        err = user_errors[0]
        raise UpstreamError(err.get("message", "Coupon preview failed"), err.get("code"), err.get("field"), user_error=True)
    return {
        "valid": bool(result.get("valid")),
        "discountAmount": result.get("discountAmount"),
        "newTotal": result.get("newTotal"),
    }
