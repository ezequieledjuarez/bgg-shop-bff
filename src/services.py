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
