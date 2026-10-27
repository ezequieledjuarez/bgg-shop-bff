import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import requests
import logging
import time
import threading
import hashlib


MAX_PAGE_SIZE = 200
DEFAULT_GRAPHQL_URL = "http://localhost:8000/graphql/"

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# Simple in-memory cache for WhoAmI results to reduce upstream calls.
# Keyed by sha256(token) -> (expiry_epoch, is_admin_bool, me_payload)
_whoami_cache = {}
_whoami_lock = threading.Lock()
# 30 minutes default TTL (seconds)
_WHOAMI_CACHE_TTL = int(os.getenv("WHOAMI_CACHE_TTL_SECONDS", 30 * 60))


class UpstreamError(Exception):
    def __init__(self, message, code="UPSTREAM_ERROR", field=None, user_error=False, response_text=None, context=None):
        super().__init__(message)
        self.code = code
        self.field = field
        self.user_error = user_error
        # Best-effort persist response_text for offline triage
        if response_text:
            try:
                import json, datetime
                # include any request_id present in context for easier correlation
                request_id = None
                if isinstance(context, dict):
                    request_id = context.get('request_id')
                out = {
                    "ts": datetime.datetime.utcnow().isoformat() + "Z",
                    "note": "upstream_error_persisted",
                    "message": str(message),
                    "code": code,
                    "field": field,
                    "context": context,
                    "request_id": request_id,
                    "text_snippet": response_text[:8000],
                }
                try:
                    with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            except Exception:
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
        )
        response.raise_for_status()
        payload = response.json()
        # Best-effort persist full response text for product queries to aid triage
        try:
            if isinstance(query, str) and 'products' in query.lower():
                try:
                    import json, datetime
                    out = {
                        "request_id": request_id,
                        "ts": datetime.datetime.utcnow().isoformat() + "Z",
                        "note": "outgoing_graphql_response_products",
                        "status_code": getattr(response, 'status_code', None),
                        "text_snippet": response.text[:8000],
                        "variables": variables,
                    }
                    with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            pass
    except (requests.RequestException, ValueError) as exc:
        # Log contextual info for triage before re-raising
        try:
            logger.error("_auth_request failed: query=%s variables=%s error=%s", query.replace('\n',' ')[:400], variables, exc)
        except Exception:
            logger.error("_auth_request failed and logging failed: %s", exc)
        raise UpstreamError(str(exc), response_text=getattr(response, 'text', None), context={"request_id": request_id}) from exc
    if payload.get("errors"):
        logger.error("_auth_request GraphQL returned errors: payload=%s", payload)
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
        tokens { token refreshToken csrfToken }
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


def list_products(
    page=1,
    page_size=50,
    search=None,
    year_published=None,
    min_players=None,
    max_players=None,
    category_id=None,
    price_min=None,
    price_max=None,
    token=None,
):
    page = _pagination_value(page, "page")
    page_size = _pagination_value(page_size, "page_size")
    if search is not None and (not str(search).strip() or len(str(search)) > 200):
        raise ValueError("search must contain between 1 and 200 characters")

    filters = {
        "search": search,
        "yearPublished": _optional_integer(year_published, "year_published", 0, 9999),
        "minPlayers": _optional_integer(min_players, "min_players", 1, 999),
        "maxPlayers": _optional_integer(max_players, "max_players", 1, 999),
        "categoryId": _optional_integer(category_id, "category_id", 1, None),
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
        $page: Int!, $pageSize: Int!, $search: String, $yearPublished: Int,
        $minPlayers: Int, $maxPlayers: Int, $categoryId: Int,
        $priceMin: Float, $priceMax: Float
    ) {
        products(
            page: $page, pageSize: $pageSize, search: $search,
            yearPublished: $yearPublished, minPlayers: $minPlayers,
            maxPlayers: $maxPlayers, categoryId: $categoryId,
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
    # Best-effort persist outgoing Products GraphQL request for offline triage
    try:
        import json, datetime
        out = {
            "request_id": request_id,
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "note": "outgoing_graphql_request_products",
            "headers": {"Authorization": (token[:20] + '...') if token and isinstance(token, str) else None},
            "variables": {"page": page, "pageSize": page_size, **filters},
            "query_snippet": query.replace('\n', ' ')[:2000],
        }
        try:
            with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(out, ensure_ascii=False) + "\n")
        except Exception:
            pass
    except Exception:
        pass
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": {"page": page, "pageSize": page_size, **filters}},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        # Log request/response context to help root-cause analysis
        try:
            masked = None
            if token and isinstance(token, str):
                masked = token[:10] + '...'
            logger.error("list_products upstream failure. page=%s page_size=%s filters=%s token=%s exc=%s",
                         page, page_size, filters, masked, exc)
        except Exception:
            logger.exception("Failed to log list_products failure")
        # Attempt to persist response text if available for offline inspection
        try:
            if 'response' in locals() and hasattr(response, 'text'):
                import json, datetime
                out = {
                    'request_id': request_id,
                    'ts': datetime.datetime.utcnow().isoformat() + 'Z',
                    'note': 'list_products request exception',
                    'status_code': getattr(response, 'status_code', None),
                    'text_snippet': response.text[:8000],
                    'filters': filters,
                }
                try:
                    with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            logger.exception("Failed to persist list_products exception response")
        raise UpstreamError(str(exc), response_text=getattr(response, 'text', None), context={"request_id": request_id}) from exc

    if payload.get("errors"):
        logger.error("list_products GraphQL returned errors: payload=%s", payload)
        # Persist the failing payload for offline inspection inside the container
        try:
            import json, datetime
            out = {
                'request_id': request_id,
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "list_products returned errors",
                "status_code": getattr(response, 'status_code', None),
                "payload": payload,
                "variables": {"page": page, "pageSize": page_size, **filters},
            }
            try:
                with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to persist list_products failing payload")
        raise UpstreamError("GraphQL upstream returned errors")

    products = (payload.get("data") or {}).get("products")
    if not products:
        # Log and persist the unexpected empty products payload for triage
        try:
            logger.error("list_products received empty products payload: %s", payload)
            import json, datetime
            out = {
                'request_id': request_id,
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "list_products returned no products data",
                "status_code": getattr(response, 'status_code', None),
                "payload": payload,
                "variables": {"page": page, "pageSize": page_size, **filters},
            }
            try:
                with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to persist empty products payload")
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
    except (KeyError, TypeError) as exc:
        logger.exception("Invalid product payload structure: %s", payload)
        raise UpstreamError("GraphQL upstream returned an invalid product payload") from exc
    # end of list_products


def _graphql_request(query, variables, token=None, op_key=None, map_wishlist_errors=False):
    request_id = str(uuid.uuid4())
    headers = {}
    if token:
        headers["Authorization"] = token
    # Prefer explicit op_key argument, otherwise forward incoming header when present
    try:
        if op_key:
            headers['X-Op-Key'] = op_key
        else:
            from flask import request as _flask_request
            found = _flask_request.headers.get('X-Op-Key') or _flask_request.headers.get('x-op-key')
            if found:
                headers['X-Op-Key'] = found
    except Exception:
        # not running in Flask request context or header missing
        pass
    # Persist a compact trace of forwarded headers for offline debugging
    try:
        import json, datetime
        trace = {
            'ts': datetime.datetime.utcnow().isoformat() + 'Z',
            'note': '_graphql_request_forwarded_headers',
            'request_id': request_id,
            'forwarded_headers': {k: (v[:20] + '...') if isinstance(v, str) and len(v) > 20 else v for k,v in headers.items()},
            'pid': os.getpid(),
            'correlation_id': None,
        }
        try:
            # try to obtain correlation id from flask g if available
            from flask import g as _g
            cid = getattr(_g, 'correlation_id', None)
            if cid:
                trace['correlation_id'] = cid
        except Exception:
            pass
        with open('/tmp/bff-calltrace.log', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception:
        pass
    try:
        # Also persist incoming request header snapshot for correlation
        from flask import request as _flask_request
        import json, datetime
        incoming = {k: (v[:40] + '...') if isinstance(v, str) and len(v) > 40 else v for k, v in dict(_flask_request.headers).items()}
        with open('/tmp/bff-calltrace.log', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'ts': datetime.datetime.utcnow().isoformat() + 'Z', 'note': '_graphql_request_incoming_headers', 'request_id': request_id, 'incoming_headers': incoming}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # Debug logging to capture outgoing GraphQL requests/responses for triage
    try:
        logger.info("Outgoing GraphQL request headers=%s variables=%s", headers, variables)
        logger.info("Outgoing GraphQL query: %s", query.replace('\n', ' ')[:1000])
    except Exception:
        # Best-effort logging; never fail the request due to logging
        pass
    # Best-effort persist outgoing GraphQL request for offline triage
    try:
        import json, datetime
        out = {
            "request_id": request_id,
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "note": "outgoing_graphql_request",
            "headers": headers,
            "variables": variables,
            "query_snippet": query.replace('\n', ' ')[:2000],
        }
        try:
            with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(out, ensure_ascii=False) + "\n")
        except Exception:
            # swallow persistence errors
            pass
    except Exception:
        pass
    try:
        # Temporary diagnostic snapshot before making the outgoing HTTP call.
        # Persist a compact diagnostic record (url, headers, variables, stack)
        # to help triage intermittent cases where headers become empty.
        try:
            import traceback, json, datetime, os

            diag = {
                "request_id": request_id,
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "outgoing_graphql_diagnostic",
                "url": os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
                "headers": headers,
                "variables": variables,
                "stack": traceback.format_stack()[-8:],
            }
            with open('/tmp/bff-proxy-diagnostic.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(diag, ensure_ascii=False) + "\n")
        except Exception:
            # swallow diagnostic failures
            pass

        logger.info("Performing GraphQL POST to %s headers=%s", os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL), headers)
        # Persist a complete outgoing snapshot for offline inspection (unique per request)
        try:
            import json as _json, datetime as _datetime, os as _os
            diag_file = f"/tmp/bff-outgoing-{request_id}.json"
            out_full = {
                "request_id": request_id,
                "ts": _datetime.datetime.utcnow().isoformat() + "Z",
                "note": "outgoing_graphql_full",
                "url": os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
                "headers": headers,
                "variables": variables,
                "query": query,
                "pid": _os.getpid(),
            }
            try:
                with open(diag_file, 'w', encoding='utf-8') as _fh:
                    _fh.write(_json.dumps(out_full, ensure_ascii=False, indent=2))
            except Exception:
                pass
        except Exception:
            pass

        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            logger.info("GraphQL response payload keys=%s", list(payload.keys()) if isinstance(payload, dict) else type(payload))
            # If the upstream returned errors or userErrors nested in data, log full payload for triage
            has_user_errors = False
            if isinstance(payload, dict):
                if payload.get('errors'):
                    has_user_errors = True
                else:
                    # check common mutation shapes for userErrors
                    data = payload.get('data') or {}
                    for v in data.values():
                        if isinstance(v, dict) and (v.get('userErrors') or v.get('errors')):
                            has_user_errors = True
                            break
            if has_user_errors:
                logger.info("GraphQL full payload for error investigation: %s", payload)
        except Exception:
            pass
    except (requests.RequestException, ValueError) as exc:
        # Log context for debugging network or parse errors
        try:
            logger.error("_graphql_request failed. headers=%s variables=%s error=%s", headers, variables, exc)
            # Attempt to log response text if available
            if 'response' in locals() and hasattr(response, 'text'):
                logger.error("_graphql_request response_text=%s", response.text[:2000])
                # Also persist the failing response to a temp file for offline inspection
                try:
                    import json, datetime
                    out = {
                        'request_id': request_id,
                        'ts': datetime.datetime.utcnow().isoformat() + 'Z',
                        'status_code': getattr(response, 'status_code', None),
                        'text_snippet': response.text[:8000],
                        'variables': variables,
                    }
                    with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            logger.exception("Failed to log _graphql_request error")
        raise UpstreamError(str(exc), response_text=getattr(response, 'text', None), context={"request_id": request_id}) from exc
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
    """
    Attempt a direct GraphQL query for a product by its numeric BGG id.
    If the upstream schema supports `productByBggId`, use it. Otherwise
    fall back to paginated `products` queries and scan for the matching id.
    Returns the same normalized product dict as `get_product_detail`.
    """
    # First, try a direct field that some backends may expose.
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
    try:
        # Debug: persist that we're attempting direct productByBggId lookup
        try:
            import json, datetime
            with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps({'ts': datetime.datetime.utcnow().isoformat() + 'Z', 'note': 'productByBggId_attempt', 'bgg_id': int(bgg_id)}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        payload = _graphql_request(query_direct, {"bggId": int(bgg_id)}, token)
        product = (payload.get("data") or {}).get("productByBggId")
        if product is None:
            # upstream does not have this field or returned null; fall through
            raise UpstreamError("Product not found by direct bggId query", "PRODUCT_NOT_FOUND")
        # reuse the existing mapping logic
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
        except (KeyError, TypeError) as exc:
            raise UpstreamError("GraphQL upstream returned an invalid product payload") from exc
    except UpstreamError as exc:
        # If upstream doesn't support the direct field, fall back to scanning products
        try:
            # page through results with reasonably large page_size to find the product
            page = 1
            page_size = 200
            max_pages = 10
            while page <= max_pages:
                try:
                    res = list_products(page=page, page_size=page_size, token=token)
                except Exception:
                    # propagate underlying upstream errors
                    raise
                items = res.get("items") if isinstance(res, dict) else []
                for item in items:
                    if str(item.get("bgg_id")) == str(bgg_id):
                        return item
                try:
                    total_pages = int(res.get("total_pages") or 0)
                    if total_pages and page >= total_pages:
                        break
                except Exception:
                    pass
                page += 1
            raise UpstreamError("The requested game does not exist", "PRODUCT_NOT_FOUND")
        except UpstreamError:
            # bubble up the not-found or upstream error
            raise


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


def checkout(shipping_mode, address, token):
    query = f"""
    mutation Checkout($address: ShippingAddressInput, $shippingMode: ShippingMode!) {{
      checkout(address: $address, shippingMode: $shippingMode) {{
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
    }, token)
    return _order_payload(payload, "checkout")


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
    invoice_url = urlunsplit((parsed.scheme, parsed.netloc, base_path + "/invoices/" + identifier, "", ""))
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
    except requests.RequestException as exc:
        raise UpstreamError(str(exc), response_text=getattr(response, 'text', None)) from exc


def check_admin(token):
    """Return True if the provided Authorization token belongs to an admin user."""
    query = """
    query WhoAmI {
      me { id email isStaff isSuperuser }
    }
    """
    # Normalize token and guard empty values
    if not token or not isinstance(token, str) or not token.strip():
        return False
    token = token.strip()

    # Compute cache key (hash token for safety)
    try:
        key = hashlib.sha256(token.encode('utf-8')).hexdigest()
    except Exception:
        key = token[:64]

    # Best-effort pre-call dump to correlate incoming request -> outgoing WhoAmI
    try:
        import json, datetime
        out = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "note": "check_admin_pre_call",
            "token_masked": (token[:20] + '...') if token and isinstance(token, str) else None,
        }
        try:
            with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(out, ensure_ascii=False) + "\n")
        except Exception:
            pass
    except Exception:
        pass

    # Try cached result
    now = time.time()
    try:
        with _whoami_lock:
            entry = _whoami_cache.get(key)
            if entry and entry[0] > now:
                # entry: (expiry, is_admin, me)
                return bool(entry[1])
    except Exception:
        # cache failures are non-fatal
        pass

    # Make upstream call(s) when cache miss. If `me` is null/invalid, retry a few
    # times before treating it as a negative result. Do NOT cache a null `me`
    # result immediately to avoid prolonged denial due to transient upstream
    # glitches.
    attempts = int(os.getenv("WHOAMI_RETRY_COUNT", 2))
    base_delay = float(os.getenv("WHOAMI_RETRY_BASE_DELAY_SECONDS", 0.25))
    last_payload = None
    for attempt in range(0, attempts + 1):
        try:
            payload = _graphql_request(query, {}, token)
        except UpstreamError as exc:
            # Persist upstream failure context for offline triage
            try:
                import json, datetime
                out = {
                    "ts": datetime.datetime.utcnow().isoformat() + "Z",
                    "note": "check_admin upstream error",
                    "error": str(exc),
                    "attempt": attempt,
                    "token_masked": (token[:10] + "...") if token and isinstance(token, str) else None,
                }
                try:
                    with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            except Exception:
                pass
            # For network/parse errors, propagate immediately (don't retry)
            raise

        # If upstream returned GraphQL errors, surface as upstream failure
        if payload.get("errors"):
            try:
                import json, datetime
                out = {
                    "ts": datetime.datetime.utcnow().isoformat() + "Z",
                    "note": "check_admin returned errors",
                    "payload": payload,
                    "attempt": attempt,
                    "token_masked": (token[:10] + "...") if token and isinstance(token, str) else None,
                }
                try:
                    with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            except Exception:
                pass
            raise UpstreamError("GraphQL upstream returned errors")

        last_payload = payload
        me = (payload.get("data") or {}).get("me")
        if isinstance(me, dict):
            # Valid response — determine admin status and cache it
            is_admin = bool(me.get("isStaff") or me.get("isSuperuser"))
            try:
                with _whoami_lock:
                    _whoami_cache[key] = (time.time() + _WHOAMI_CACHE_TTL, is_admin, me)
            except Exception:
                pass
            return is_admin

        # me is null or invalid — persist a detailed note but DO NOT cache yet
        try:
            import json, datetime
            out = {
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "check_admin invalid me payload",
                "payload": payload,
                "attempt": attempt,
                "token_masked": (token[:10] + "...") if token and isinstance(token, str) else None,
            }
            try:
                with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            except Exception:
                pass
        except Exception:
            pass

        # If we have more attempts left, wait a bit and retry
        if attempt < attempts:
            try:
                time.sleep(base_delay * (2 ** attempt))
                continue
            except Exception:
                # If sleep is interrupted, break and treat as negative below
                pass

        # Exhausted retries — cache a negative result (but store the raw me value)
        try:
            with _whoami_lock:
                _whoami_cache[key] = (time.time() + _WHOAMI_CACHE_TTL, False, me)
        except Exception:
            pass
        return False


def list_promotions():
    query = """
    query ListPromotions {
      promotions { id name discountPercent active }
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


def update_promotion(promotion_id, payload, token=None):
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
    variables = {"id": promotion_id, "input": payload}
    resp = _graphql_request(query, variables, token)
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


# Admin mutations and management helpers
def create_product(payload, token=None, op_key=None):
    # Basic validation
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    # Debug: persist incoming token/op_key for triage
    try:
        import json, datetime
        dbg = {
            'ts': datetime.datetime.utcnow().isoformat() + 'Z',
            'note': 'create_product_incoming_debug',
            'token_present': bool(token),
            'token_masked': (token[:10] + '...') if token and isinstance(token, str) and len(token) > 13 else token,
            'op_key_present': bool(op_key),
            'op_key_masked': (op_key[:6] + '...' + op_key[-4:]) if op_key and isinstance(op_key, str) else op_key,
            'payload_sample': {'name': payload.get('name')}
        }
        with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(dbg, ensure_ascii=False) + "\n")
    except Exception:
        pass
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
        # Debug: record attempt and success markers to help triage missing file writes
        try:
            with open('/tmp/bff-created-products-debug.log', 'a', encoding='utf-8') as dbgfh:
                dbgfh.write(json.dumps({"ts": datetime.datetime.utcnow().isoformat() + 'Z', "note": "create_product_write_attempt", "rec": rec}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        try:
            with open('/tmp/bff-created-products.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            try:
                with open('/tmp/bff-created-products-debug.log', 'a', encoding='utf-8') as dbgfh:
                    dbgfh.write(json.dumps({"ts": datetime.datetime.utcnow().isoformat() + 'Z', "note": "create_product_write_failed", "error": str(e)}, ensure_ascii=False) + "\n")
            except Exception:
                pass
        else:
            try:
                with open('/tmp/bff-created-products-debug.log', 'a', encoding='utf-8') as dbgfh:
                    dbgfh.write(json.dumps({"ts": datetime.datetime.utcnow().isoformat() + 'Z', "note": "create_product_write_success", "bgg_id": product.get('bggId')}, ensure_ascii=False) + "\n")
            except Exception:
                pass
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


def adjust_variant_stock(product_id, variant_id, new_stock, token=None):
    try:
        new_stock_int = int(new_stock)
    except (ValueError, TypeError):
        raise ValueError("new_stock must be an integer")
    query = """
    mutation AdjustVariantStock($productId: ID!, $variantId: ID!, $newStock: Int!) {
      adjustVariantStock(productId: $productId, variantId: $variantId, newStock: $newStock) {
        success
        errors { field code message }
      }
    }
    """
    variables = {"productId": product_id, "variantId": variant_id, "newStock": new_stock_int}
    payload_resp = _graphql_request(query, variables, token)
    if payload_resp.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    result = (payload_resp.get("data") or {}).get("adjustVariantStock")
    if not isinstance(result, dict):
        raise UpstreamError("GraphQL upstream returned an invalid adjustVariantStock payload")
    errors = result.get("errors") or []
    if errors:
        err = errors[0]
        raise UpstreamError(err.get("message", "Adjust stock failed"), err.get("code"), err.get("field"), user_error=True)
    return {"success": bool(result.get("success"))}


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
