from . import proxy


def register_account(payload):
    return proxy.register_account(payload)


def authenticate_account(payload):
    return proxy.authenticate_account(payload)


def list_products(**filters):
    return proxy.list_products(**filters)


def get_product_detail(slug):
    return proxy.get_product_detail(slug)


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
def admin_list_products(page=1, page_size=20, q=None):
    # Reuse the public list_products proxy for now; admin may require more fields later
    return proxy.list_products(page=page, page_size=page_size, search=q)


def admin_create_product(payload):
    return proxy.create_product(payload)


def admin_update_product(product_id, payload):
    return proxy.update_product(product_id, payload)


def adjust_variant_stock(product_id, variant_id, new_stock):
    return proxy.adjust_variant_stock(product_id, variant_id, new_stock)


# Promotions
def admin_list_promotions():
    return proxy.list_promotions()


def admin_create_promotion(payload):
    return proxy.create_promotion(payload)


def admin_update_promotion(promotion_id, payload):
    return proxy.update_promotion(promotion_id, payload)


def admin_apply_coupon_preview(code, **kwargs):
    return proxy.apply_coupon_preview(code, kwargs)
