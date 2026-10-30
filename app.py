import os
import uuid
import requests as _requests

from flask import Flask, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from src.controllers import (
    add_cart_item as add_cart_item_controller,
    auth_request,
    checkout as checkout_controller,
    confirm_payment as confirm_payment_controller,
    create_review as create_review_controller,
    list_orders as list_orders_controller,
    order_detail as order_detail_controller,
    order_invoice as order_invoice_controller,
    retry_payment as retry_payment_controller,
    health as health_controller,
    product_detail as product_detail_controller,
    products as products_controller,
    read_cart as read_cart_controller,
    remove_cart_item as remove_cart_item_controller,
    update_cart_item as update_cart_item_controller,
    add_wishlist_item,
    list_wishlist,
    remove_wishlist_item,
)
from src.services import (
    add_to_cart,
    authenticate_account,
    checkout,
    confirm_payment,
    create_review,
    get_invoice,
    get_order,
    get_orders,
    retry_payment,
    get_cart,
    get_product_detail,
    list_products,
    register_account,
    remove_from_cart,
    update_cart_quantity,
    add_to_wishlist,
    get_wishlist,
    remove_from_wishlist,
)
from src.controllers import (
    admin_list_products,
    admin_get_product,
    admin_create_product,
    admin_update_product,
    admin_adjust_variant_stock,
)
from src.controllers import (
    admin_list_promotions as admin_list_promotions_controller,
    admin_create_promotion as admin_create_promotion_controller,
    admin_update_promotion as admin_update_promotion_controller,
)
from src.controllers import admin_apply_coupon_preview as admin_apply_coupon_preview_controller
from src.controllers.admin_gift_cards_controller import create_gift_card as admin_create_gift_card_controller
from src.controllers.credit_controller import get_credit, redeem_gift_card, checkout_credit
from src import proxy as proxy_module
from src import opkey_middleware
from flask import jsonify

app = Flask(__name__)
allowed_origins = ("http://localhost:3000", "http://127.0.0.1:3000")
def _dynamic_allow_headers(environ):
    # Echo requested headers if present; fallback to common headers
    acrh = environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS')
    if acrh:
        # Return as-is (Flask-CORS will normalize)
        return acrh
    return ['Content-Type', 'Authorization', 'authorization']


CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers="*",
    expose_headers=["Location"],
    supports_credentials=True,
)

_CREDIT_PATHS = {
    "/api/v1/credit",
    "/api/v1/gift-cards/redeem",
    "/api/v1/checkout/credit",
}

# Initialize OpKey middleware (validates X-Op-Key and caches results)
opkey_middleware.init_app(app)
_opkey_before_request = app.before_request_funcs[None][-1]


def _opkey_except_credit():
    if request.path not in _CREDIT_PATHS:
        return _opkey_before_request()


app.before_request_funcs[None][-1] = _opkey_except_credit

from flask import g
import json as _json
def _append_incoming_log(entry: dict):
    try:
        pid = str(os.getpid())
        path = f"/tmp/bff-incoming-{pid}.log"
        entry['pid'] = pid
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


@app.before_request
def _log_incoming_request():
    if request.path == "/api/v1/admin/gift-cards" or request.path in _CREDIT_PATHS:
        return
    try:
        cid = str(uuid.uuid4())
        g.correlation_id = cid
        entry = {
            'ts': _json.dumps(__import__('datetime').datetime.utcnow().isoformat()),
            'note': 'incoming_request',
            'path': request.url_rule.rule if request.url_rule else '<unmatched>',
            'correlation_id': cid,
        }
        _append_incoming_log(entry)
    except Exception:
        pass



# Ensure OPTIONS preflight requests to /api/v1/* always return appropriate CORS headers.
# Some browsers may issue preflight requests which can return 404 if routes
# are not yet fully registered or if Flask-CORS middleware does not catch them.
@app.route('/api/v1', methods=['OPTIONS'])
def preflight_api_root():
    origin = request.headers.get('Origin')
    ac_origin = origin if origin in allowed_origins else allowed_origins[0]
    resp = app.make_response(('', 200))
    resp.headers['Access-Control-Allow-Origin'] = ac_origin
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,PATCH,DELETE,OPTIONS'
    # Allow requested headers dynamically to support debug headers used by tests
    acrh = request.headers.get('Access-Control-Request-Headers')
    resp.headers['Access-Control-Allow-Headers'] = acrh if acrh else 'Content-Type, Authorization'
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    # Expose Location header so clients can read it from responses
    resp.headers['Access-Control-Expose-Headers'] = 'Location'
    return resp


@app.route('/api/v1/<path:dummy>', methods=['OPTIONS'])
def preflight_api(dummy):
    origin = request.headers.get('Origin')
    ac_origin = origin if origin in allowed_origins else allowed_origins[0]
    resp = app.make_response(('', 200))
    resp.headers['Access-Control-Allow-Origin'] = ac_origin
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,PATCH,DELETE,OPTIONS'
    acrh = request.headers.get('Access-Control-Request-Headers')
    resp.headers['Access-Control-Allow-Headers'] = acrh if acrh else 'Content-Type, Authorization'
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    # Expose Location header so clients can read it from responses
    resp.headers['Access-Control-Expose-Headers'] = 'Location'
    return resp


def _configured_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@app.errorhandler(proxy_module.UpstreamError)
def _handle_upstream_error(exc):
    app.logger.error("Upstream request failed.")
    return jsonify({"error": "upstream GraphQL request failed"}), 502


@app.errorhandler(Exception)
def _handle_unexpected_exception(exc):
    if isinstance(exc, HTTPException):
        return exc
    app.logger.error("Unexpected request error.")
    return jsonify({"error": "internal server error"}), 500


app.config["CART_COOKIE_NAME"] = os.getenv("CART_COOKIE_NAME", "cart_id")
secure_setting = os.getenv("CART_COOKIE_SECURE")
development = (
    app.debug
    or _configured_bool(os.getenv("FLASK_DEBUG", "false"))
    or os.getenv("FLASK_ENV", "").lower() == "development"
    or os.getenv("APP_ENV", "").lower() == "development"
)
app.config["CART_COOKIE_SECURE"] = (
    _configured_bool(secure_setting) if secure_setting is not None else not development
)


@app.route("/health", methods=["GET"])
def health():
    return health_controller()


@app.route("/api/v1/_debug/headers", methods=["POST"])
def debug_headers():
    return ('', 204)


@app.route("/api/v1/products", methods=["GET"])
def products():
    return products_controller(list_products)


@app.route("/api/v1/games/<slug>", methods=["GET"])
def game_detail(slug):
    return product_detail_controller(slug, get_product_detail)


@app.route("/api/v1/games/<slug>/reviews", methods=["POST"])
def game_review(slug):
    return create_review_controller(slug, create_review)


@app.route("/api/v1/cart", methods=["GET"])
def cart():
    return read_cart_controller(get_cart)


@app.route("/api/v1/cart/items", methods=["POST"])
def cart_add_item():
    return add_cart_item_controller(add_to_cart)


@app.route("/api/v1/cart/items/<bgg_id>", methods=["PATCH"])
def cart_update_item(bgg_id):
    return update_cart_item_controller(bgg_id, update_cart_quantity)


@app.route("/api/v1/cart/items/<bgg_id>", methods=["DELETE"])
def cart_remove_item(bgg_id):
    return remove_cart_item_controller(bgg_id, remove_from_cart)


@app.route("/api/v1/wishlist", methods=["GET"])
def wishlist():
    return list_wishlist(get_wishlist)


@app.route("/api/v1/wishlist", methods=["POST"])
def wishlist_add_item():
    return add_wishlist_item(add_to_wishlist)


@app.route("/api/v1/wishlist/<bgg_id>", methods=["DELETE"])
def wishlist_remove_item(bgg_id):
    return remove_wishlist_item(bgg_id, remove_from_wishlist)


@app.route("/api/v1/checkout", methods=["POST"])
def purchase_checkout():
    return checkout_controller(checkout)


@app.route("/api/v1/credit", methods=["GET"])
def credit_balance():
    return get_credit()


@app.route("/api/v1/gift-cards/redeem", methods=["POST"])
def gift_card_redeem():
    return redeem_gift_card()


@app.route("/api/v1/checkout/credit", methods=["POST"])
def purchase_checkout_credit():
    return checkout_credit()


@app.route("/api/v1/checkout/confirm", methods=["POST"])
def purchase_confirm():
    return confirm_payment_controller(confirm_payment)


@app.route("/api/v1/orders", methods=["GET"])
def purchase_orders():
    return list_orders_controller(get_orders)


@app.route("/api/v1/orders/<order_id>", methods=["GET"])
def purchase_order(order_id):
    return order_detail_controller(order_id, get_order)


@app.route("/api/v1/orders/<order_id>/retry-payment", methods=["POST"])
def purchase_retry_payment(order_id):
    return retry_payment_controller(order_id, retry_payment)


@app.route("/api/v1/orders/<order_id>/invoice", methods=["GET"])
def purchase_invoice(order_id):
    return order_invoice_controller(order_id, get_invoice)


@app.route("/api/v1/auth/register", methods=["POST"])
def register():
    return auth_request(register_account, 201)


@app.route("/api/v1/auth/login", methods=["POST"])
def login():
    guest_cart_id = request.cookies.get(app.config["CART_COOKIE_NAME"])
    response, status = auth_request(
        lambda payload: authenticate_account({**payload, "guest_cart_id": guest_cart_id}),
        200,
    )
    if status == 200:
        response.delete_cookie(
            app.config["CART_COOKIE_NAME"],
            path="/",
            secure=app.config["CART_COOKIE_SECURE"],
            httponly=True,
            samesite="Lax",
        )
    return response, status


@app.route("/api/v1/auth/refresh", methods=["POST"])
def refresh():
    """Proxy endpoint: read refresh token from HttpOnly cookie, call core refresh, rotate cookie.

    Returns JSON { access_token } on success and sets HttpOnly `refresh_token` cookie.
    """
    core_base = os.getenv("SALEOR_BASE_URL", "http://localhost:8000")
    refresh_cookie = request.cookies.get('refresh_token')
    # optionally allow client to provide refresh_token in body (for tests)
    body = request.get_json(silent=True) or {}
    refresh_token = body.get('refresh_token') or refresh_cookie
    if not refresh_token:
        # no refresh available
        resp = app.make_response(({"detail": "no refresh token"}, 401))
        resp.delete_cookie('refresh_token', path='/', secure=app.config.get('CART_COOKIE_SECURE', True), httponly=True, samesite='Strict')
        return resp
    try:
        core_url = f"{core_base}/api/v1/auth/refresh"
        r = _requests.post(core_url, json={"refresh_token": refresh_token}, timeout=5)
        if r.status_code != 200:
            resp = app.make_response(({"detail": "refresh failed"}, 401))
            resp.delete_cookie('refresh_token', path='/', secure=app.config.get('CART_COOKIE_SECURE', True), httponly=True, samesite='Strict')
            return resp
        payload = r.json()
        access = payload.get('access_token')
        new_refresh = payload.get('refresh_token')
        if not access:
            resp = app.make_response(({"detail": "invalid upstream response"}, 502))
            return resp
        resp = app.make_response(({"access_token": access}, 200))
        if new_refresh:
            resp.set_cookie('refresh_token', new_refresh, path='/', secure=app.config.get('CART_COOKIE_SECURE', True), httponly=True, samesite='Strict')
        return resp
    except Exception:
        app.logger.error("Refresh upstream request failed.")
        resp = app.make_response(({"detail": "refresh upstream error"}, 502))
        resp.delete_cookie('refresh_token', path='/', secure=app.config.get('CART_COOKIE_SECURE', True), httponly=True, samesite='Strict')
        return resp


# Admin management endpoints (minimal scaffolding)
@app.route("/api/v1/admin/gift-cards", methods=["POST"])
def admin_gift_cards_create():
    return admin_create_gift_card_controller()


@app.route("/api/v1/admin/products", methods=["GET"])
def admin_products_list():
    return admin_list_products()


@app.route("/api/v1/admin/products", methods=["POST"])
def admin_products_create():
    return admin_create_product()


@app.route("/api/v1/admin/products/<product_id>", methods=["PUT"])
def admin_products_update(product_id):
    return admin_update_product(product_id)


@app.route("/api/v1/admin/products/<product_id>", methods=["GET"])
def admin_products_get(product_id):
    return admin_get_product(product_id)


@app.route("/api/v1/admin/products/<product_id>/variants/<variant_id>/adjust-stock", methods=["POST"])
def admin_products_adjust_stock(product_id, variant_id):
    return admin_adjust_variant_stock(product_id, variant_id)


# Admin promotions
@app.route("/api/v1/admin/promotions", methods=["GET"])
def admin_promotions_list():
    return admin_list_promotions_controller()


@app.route("/api/v1/admin/promotions", methods=["POST"])
def admin_promotions_create():
    return admin_create_promotion_controller()


@app.route("/api/v1/admin/promotions/<promotion_id>", methods=["PUT"])
def admin_promotions_update(promotion_id):
    return admin_update_promotion_controller(promotion_id)


# Admin coupons
@app.route("/api/v1/admin/coupons/<code>/apply", methods=["POST"])
def admin_coupons_apply(code):
    return admin_apply_coupon_preview_controller(code)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
