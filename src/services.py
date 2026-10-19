from . import proxy


def register_account(payload):
    return proxy.register_account(payload)


def authenticate_account(payload):
    return proxy.authenticate_account(payload)


def list_products(**filters):
    return proxy.list_products(**filters)
