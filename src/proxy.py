import os

import requests


MAX_PAGE_SIZE = 100
DEFAULT_GRAPHQL_URL = "http://localhost:8000/graphql/"


class UpstreamError(Exception):
    def __init__(self, message, code="UPSTREAM_ERROR"):
        super().__init__(message)
        self.code = code


def _required_text(payload, name, minimum=1, maximum=254):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    value = value.strip()
    if len(value) < minimum or len(value) > maximum:
        raise ValueError(f"{name} has an invalid length")
    return value


def _auth_request(query, variables):
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": variables},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamError(str(exc)) from exc
    if payload.get("errors"):
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
    result = _auth_result(_auth_request(query, {
        "input": {"email": email, "password": password}
    }), "login")
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
    if name == "page_size" and parsed > MAX_PAGE_SIZE:
        raise ValueError(f"{name} must not exceed {MAX_PAGE_SIZE}")
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
    page_size=20,
    search=None,
    year_published=None,
    min_players=None,
    max_players=None,
    category_id=None,
    price_min=None,
    price_max=None,
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
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": {"page": page, "pageSize": page_size, **filters}},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamError(str(exc)) from exc

    if payload.get("errors"):
        raise UpstreamError("GraphQL upstream returned errors")
    products = (payload.get("data") or {}).get("products")
    if not products:
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
        raise UpstreamError("GraphQL upstream returned an invalid product payload") from exc


def _graphql_request(query, variables, token=None):
    headers = {"Authorization": token} if token else {}
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamError(str(exc)) from exc
    return payload


def get_product_detail(slug):
    query = """
    query ProductBySlug($slug: String!) {
      productBySlug(slug: $slug) {
        name releaseYear minPlayers maxPlayers playingTimeMinutes minAge
        weight category price publisher imageUrl
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
            "name": product["name"],
            "weight": product["weight"],
            "category": product["category"],
            "price": product["price"],
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
