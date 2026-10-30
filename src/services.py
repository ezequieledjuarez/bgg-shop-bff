from . import proxy


def register_account(payload):
    return proxy.register_account(payload)


def authenticate_account(payload):
    return proxy.authenticate_account(payload)


def list_products(**filters):
    return proxy.list_products(**filters)


def get_product_detail(slug):
    return proxy.get_product_detail(slug)


def get_product_by_bgg_id(bgg_id, token=None):
    return proxy.get_product_by_bgg_id(bgg_id, token)


def create_review(slug, rating, body, token):
    return proxy.create_review(slug, rating, body, token)


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
    return proxy.checkout(shipping_mode, address, token)


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
    # If an op_key was provided but no Authorization token, allow using
    # a configured internal admin token so the BFF can perform upstream
    # GraphQL admin mutations during testing/dev. Set via env `BFF_ADMIN_TOKEN`.
    if not token and op_key:
        import os
        token = os.getenv("BFF_ADMIN_TOKEN")
        if not token:
            # try reading a token file for quick local testing
            try:
                with open('/tmp/bff_admin_token', 'r', encoding='utf-8') as fh:
                    token = fh.read().strip()
            except Exception:
                token = None
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
    if not token and op_key:
        import os
        token = os.getenv("BFF_ADMIN_TOKEN")
        if not token:
            try:
                with open('/tmp/bff_admin_token', 'r', encoding='utf-8') as fh:
                    token = fh.read().strip()
            except Exception:
                token = None
    return proxy.update_product(product_id, payload, token, op_key=op_key)


def adjust_variant_stock(product_id, variant_id, new_stock, token=None):
    return proxy.adjust_variant_stock(product_id, variant_id, new_stock, token)


# Promotions
def admin_list_promotions():
    return proxy.list_promotions()


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
    if not token and op_key:
        import os
        token = os.getenv("BFF_ADMIN_TOKEN")
        if not token:
            try:
                with open('/tmp/bff_admin_token', 'r', encoding='utf-8') as fh:
                    token = fh.read().strip()
            except Exception:
                token = None
    return proxy.create_promotion(payload, token, op_key=op_key)


def admin_update_promotion(promotion_id, payload):
    token = payload.get("_auth_token") if isinstance(payload, dict) else None
    if isinstance(payload, dict) and "_auth_token" in payload:
        payload = {k: v for k, v in payload.items() if k != "_auth_token"}
    return proxy.update_promotion(promotion_id, payload, token)


def admin_apply_coupon_preview(code, **kwargs):
    return proxy.apply_coupon_preview(code, kwargs)
