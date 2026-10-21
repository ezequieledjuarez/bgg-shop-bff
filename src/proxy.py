import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import requests


MAX_PAGE_SIZE = 100
DEFAULT_GRAPHQL_URL = "http://localhost:8000/graphql/"


class UpstreamError(Exception):
    def __init__(self, message, code="UPSTREAM_ERROR", field=None, user_error=False):
        super().__init__(message)
        self.code = code
        self.field = field
        self.user_error = user_error


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
        raise UpstreamError("GraphQL upstream returned an invalid product payload") from exc


def _graphql_request(query, variables, token=None, map_wishlist_errors=False):
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
        name releaseYear minPlayers maxPlayers playingTimeMinutes minAge
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
        raise UpstreamError(str(exc)) from exc
