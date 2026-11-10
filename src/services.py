from . import proxy
from .catalog_cache import catalog_response


def register_account(payload):
    return proxy.register_account(payload)


def authenticate_account(payload):
    return proxy.authenticate_account(payload)


def confirm_email_verification(token, caller):
    return proxy.confirm_email_verification(token, caller)


def resend_email_verification(email, caller):
    return proxy.resend_email_verification(email, caller)


def create_chat_conversation(token=None, cookie_value=None):
    return proxy.create_chat_conversation(token, cookie_value)


def record_chat_exchange(
    conversation_id,
    user_message,
    assistant_message,
    token=None,
    cookie_value=None,
    sources=None,
):
    return proxy.record_chat_exchange(
        conversation_id,
        user_message,
        assistant_message,
        token,
        cookie_value,
        sources,
    )


def recommend_catalog_products(filters, token=None):
    result = proxy.list_products(page=1, page_size=50, token=token, **filters)
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        raise proxy.UpstreamError("Catalog returned an invalid product list")
    return items


def list_products(**filters):
    return catalog_response(
        "products",
        filters,
        lambda: proxy.list_products(**filters),
    )


def list_product_categories():
    return proxy.list_product_categories()


def list_product_publishers():
    return proxy.list_product_publishers()


def list_available_coupons():
    return proxy.list_available_coupons()


def get_product_detail(slug):
    return catalog_response(
        "game-detail",
        {"slug": slug},
        lambda: proxy.get_product_detail(slug),
    )


def get_product_by_bgg_id(bgg_id, token=None):
    return proxy.get_product_by_bgg_id(bgg_id, token)


def get_stock_movement_status(movement_id, token=None):
    return proxy.get_stock_movement_status(movement_id, token)


def create_review(slug, rating, body, token):
    return proxy.create_review(slug, rating, body, token)


def admin_list_reviews(filters, token):
    return proxy.list_admin_reviews(filters, token)


def admin_moderate_review(review_id, action, token):
    return proxy.moderate_admin_review(review_id, action, token)


def get_cart(cart_id=None, token=None):
    return proxy.get_cart(cart_id, token)


def add_to_cart(bgg_id, quantity, cart_id=None, token=None):
    return proxy.add_to_cart(bgg_id, quantity, cart_id, token)


def update_cart_quantity(bgg_id, quantity, cart_id=None, token=None):
    return proxy.update_cart_quantity(bgg_id, quantity, cart_id, token)


def remove_from_cart(bgg_id, cart_id=None, token=None):
    return proxy.remove_from_cart(bgg_id, cart_id, token)


def get_wishlist(token):
    return proxy.get_wishlist(token)


def add_to_wishlist(bgg_id, token):
    return proxy.add_to_wishlist(bgg_id, token)


def remove_from_wishlist(bgg_id, token):
    return proxy.remove_from_wishlist(bgg_id, token)


def checkout(shipping_mode, address, token):
    from flask import g, has_request_context, request

    coupon_code = None
    checkout_key = None
    coupon_provided = False
    if has_request_context():
        coupon_provided = hasattr(g, "checkout_coupon_code")
        coupon_code = getattr(g, "checkout_coupon_code", None)
        checkout_key = request.headers.get("X-Op-Key")
    if coupon_provided:
        if not isinstance(coupon_code, str) or not coupon_code or len(coupon_code) > 64:
            raise proxy.UpstreamError(
                "A valid coupon_code is required.", "INVALID", user_error=True
            )
        if not checkout_key or len(checkout_key) > 512:
            raise proxy.UpstreamError(
                "X-Op-Key is required for coupon checkout.",
                "INVALID",
                field="X-Op-Key",
                user_error=True,
            )
    return proxy.checkout(
        shipping_mode, address, token, coupon_code=coupon_code,
        checkout_key=checkout_key,
    )


def preview_coupon(code, token):
    return proxy.preview_coupon(code, token)


def retry_payment(order_id, token):
    return proxy.retry_payment(order_id, token)


def confirm_payment(order_id, payment_id, token):
    return proxy.confirm_payment(order_id, payment_id, token)


def get_orders(token):
    return proxy.get_orders(token)


def get_order(order_id, token):
    return proxy.get_order(order_id, token)


def get_invoice(order_id, token):
    return proxy.get_invoice(order_id, token)


def check_admin(token):
    return proxy.check_admin(token)


# Admin / management wrappers
def admin_list_products(page=1, page_size=50, q=None, token=None, year_published=None,
                        min_players=None, max_players=None, category_id=None,
                        price_min=None, price_max=None, **kwargs):
    # Reuse the public list_products proxy for now; admin may require more fields later
    # Forward all supported filters to the proxy and include the optional token.
    # Accept and forward any extra kwargs to avoid unexpected keyword errors
    params = {
        'page': page,
        'page_size': page_size,
        'search': q,
        'year_published': year_published,
        'min_players': min_players,
        'max_players': max_players,
        'category_id': category_id,
        'price_min': price_min,
        'price_max': price_max,
        'token': token,
    }
    # Merge any additional kwargs provided by callers (defensive)
    params.update(kwargs or {})
    return proxy.list_products(**params)


def admin_create_product(payload):
    # token must be provided by the controller (from Authorization header)
    token = payload.get("_auth_token") if isinstance(payload, dict) else None
    op_key = payload.get("_op_key") if isinstance(payload, dict) else None
    # If DTO returned a non-dict, try reading Flask request headers as fallback
    if not isinstance(payload, dict):
        try:
            from flask import request as _flask_request
            if not token:
                token = _flask_request.headers.get('Authorization')
            if not op_key:
                op_key = _flask_request.headers.get('X-Op-Key') or _flask_request.headers.get('x-op-key')
        except Exception:
            pass
    # remove internal helper keys if present
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in ("_auth_token", "_op_key")}
    return proxy.create_product(payload, token, op_key=op_key)


def admin_update_product(product_id, payload):
    token = payload.get("_auth_token") if isinstance(payload, dict) else None
    op_key = payload.get("_op_key") if isinstance(payload, dict) else None
    if not isinstance(payload, dict):
        try:
            from flask import request as _flask_request
            if not token:
                token = _flask_request.headers.get('Authorization')
            if not op_key:
                op_key = _flask_request.headers.get('X-Op-Key') or _flask_request.headers.get('x-op-key')
        except Exception:
            pass
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in ("_auth_token", "_op_key")}
    return proxy.update_product(product_id, payload, token, op_key=op_key)


def adjust_product_stock(product_id, movement_id, direction, quantity, token=None):
    return proxy.adjust_product_stock(product_id, movement_id, direction, quantity, token)


# Promotions
def admin_list_promotions():
    return proxy.list_promotions()


def admin_list_audit(filters, token=None, op_key=None):
    return proxy.list_admin_audit(filters, token, op_key=op_key)


def admin_get_sales_metrics(filters, token=None, op_key=None):
    return proxy.get_admin_sales_metrics(filters, token, op_key=op_key)


def admin_get_sales_categories(token=None, op_key=None):
    return proxy.get_admin_sales_categories(token, op_key=op_key)


def _admin_user_error(payload):
    for error in payload.get("errors") or []:
        extensions = error.get("extensions") if isinstance(error, dict) else None
        code = extensions.get("code") if isinstance(extensions, dict) else None
        if code in ("UNAUTHENTICATED", "FORBIDDEN", "INVALID", "NOT_FOUND",
                    "LAST_ACTIVE_SUPERUSER"):
            field = extensions.get("field")
            return proxy.UpstreamError(
                "User management request rejected",
                code,
                field=[field] if isinstance(field, str) else None,
                user_error=True,
            )
        break
    return proxy.UpstreamError("GraphQL upstream returned errors")


def _admin_user_projection(user):
    if not isinstance(user, dict):
        raise proxy.UpstreamError("GraphQL upstream returned an invalid user")
    fields = {
        "id": ("id",),
        "email": ("email",),
        "first_name": ("firstName", "first_name"),
        "last_name": ("lastName", "last_name"),
        "is_active": ("isActive", "is_active"),
        "is_staff": ("isStaff", "is_staff"),
        "is_superuser": ("isSuperuser", "is_superuser"),
    }
    result = {}
    for output, aliases in fields.items():
        value = next((user[key] for key in aliases if key in user), None)
        if output == "id":
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise proxy.UpstreamError("GraphQL upstream returned an invalid user")
            value = str(value)
        elif output in ("email", "first_name", "last_name"):
            if not isinstance(value, str):
                raise proxy.UpstreamError("GraphQL upstream returned an invalid user")
        elif type(value) is not bool:
            raise proxy.UpstreamError("GraphQL upstream returned an invalid user")
        result[output] = value
    return result


def admin_list_users(filters, token):
    query = """
    query AdminUsers($search: String, $cursor: String, $limit: Int) {
      adminUsers(search: $search, cursor: $cursor, limit: $limit) {
        items { id email firstName lastName isActive isStaff isSuperuser }
        nextCursor
      }
    }
    """
    payload = proxy._graphql_request(query, filters, token)
    if payload.get("errors"):
        raise _admin_user_error(payload)
    page = (payload.get("data") or {}).get("adminUsers")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise proxy.UpstreamError("GraphQL upstream returned an invalid user page")
    next_cursor = page.get("nextCursor", page.get("next_cursor"))
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise proxy.UpstreamError("GraphQL upstream returned an invalid user page")
    return {
        "items": [_admin_user_projection(user) for user in page["items"]],
        "next_cursor": next_cursor,
    }


def admin_update_user_privilege(user_id, privilege, enabled, token):
    query = """
    mutation AdminUpdateUserPrivilege($userId: ID!, $privilege: AdminUserPrivilege!, $enabled: Boolean!) {
      adminUpdateUserPrivilege(userId: $userId, privilege: $privilege, enabled: $enabled) {
        user { id email firstName lastName isActive isStaff isSuperuser }
        userErrors { code field message }
      }
    }
    """
    payload = proxy._graphql_request(
        query,
        {"userId": user_id, "privilege": privilege, "enabled": enabled},
        token,
    )
    if payload.get("errors"):
        raise _admin_user_error(payload)
    result = (payload.get("data") or {}).get("adminUpdateUserPrivilege")
    if not isinstance(result, dict):
        raise proxy.UpstreamError("GraphQL upstream returned an invalid privilege result")
    errors = result.get("userErrors") or []
    if errors:
        error = errors[0] if isinstance(errors[0], dict) else {}
        code = error.get("code")
        if code in ("UNAUTHENTICATED", "FORBIDDEN", "INVALID", "NOT_FOUND",
                    "LAST_ACTIVE_SUPERUSER"):
            field = error.get("field")
            raise proxy.UpstreamError(
                "User management request rejected",
                code,
                field=[field] if isinstance(field, str) else None,
                user_error=True,
            )
        raise proxy.UpstreamError("GraphQL upstream returned errors")
    return _admin_user_projection(result.get("user"))


def admin_list_coupons(token=None, op_key=None):
    return proxy.list_admin_coupons(token, op_key=op_key)


def admin_create_coupon(payload):
    token = payload.get("_auth_token") if isinstance(payload, dict) else None
    op_key = payload.get("_op_key") if isinstance(payload, dict) else None
    data = {key: value for key, value in payload.items() if key not in ("_auth_token", "_op_key")}
    return proxy.create_admin_coupon(data, token, op_key=op_key)


def admin_update_coupon(coupon_id, payload):
    token = payload.get("_auth_token") if isinstance(payload, dict) else None
    op_key = payload.get("_op_key") if isinstance(payload, dict) else None
    data = {key: value for key, value in payload.items() if key not in ("_auth_token", "_op_key")}
    return proxy.update_admin_coupon(coupon_id, data, token, op_key=op_key)


def admin_create_promotion(payload):
    token = payload.get("_auth_token") if isinstance(payload, dict) else None
    op_key = payload.get("_op_key") if isinstance(payload, dict) else None
    if not isinstance(payload, dict):
        try:
            from flask import request as _flask_request
            if not token:
                token = _flask_request.headers.get('Authorization')
            if not op_key:
                op_key = _flask_request.headers.get('X-Op-Key') or _flask_request.headers.get('x-op-key')
        except Exception:
            pass
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in ("_auth_token", "_op_key")}
    return proxy.create_promotion(payload, token, op_key=op_key)


def admin_update_promotion(promotion_id, payload):
    token = payload.get("_auth_token") if isinstance(payload, dict) else None
    op_key = payload.get("_op_key") if isinstance(payload, dict) else None
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in ("_auth_token", "_op_key")}
    return proxy.update_promotion(promotion_id, payload, token, op_key=op_key)


def admin_apply_coupon_preview(code, **kwargs):
    return proxy.apply_coupon_preview(code, kwargs)
