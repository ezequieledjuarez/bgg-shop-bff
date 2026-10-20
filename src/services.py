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
