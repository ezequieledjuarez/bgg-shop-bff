import os

import requests


MAX_PAGE_SIZE = 100
DEFAULT_GRAPHQL_URL = "http://localhost:8000/graphql/"


class UpstreamError(Exception):
    pass


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
