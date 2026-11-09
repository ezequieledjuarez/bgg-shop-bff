import hashlib
import hmac
import json
import os
import threading
import uuid
import requests as _requests
from datetime import datetime
from pathlib import Path

from flask import Flask, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
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
from src.controllers.chatbot_controller import (
    create_conversation as create_chat_conversation_controller,
    send_message as send_chat_message_controller,
)
from src.controllers.chatbot_conversations_controller import (
    delete_conversation as delete_chat_conversation_controller,
    get_conversation as get_chat_conversation_controller,
)
from src.controllers.auth_controller import current_user as auth_current_user_controller
from src.controllers.reviews_controller import (
    admin_list_reviews as admin_list_reviews_controller,
    admin_moderate_review as admin_moderate_review_controller,
)
from src.services import (
    add_to_cart,
    authenticate_account,
    checkout,
    confirm_payment,
    create_review,
    admin_list_reviews,
    admin_moderate_review,
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
    create_chat_conversation,
    record_chat_exchange,
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
from src.controllers.admin_coupons_controller import list_available_coupons as list_available_coupons_controller
from src.controllers.admin_coupons_controller import preview_current_cart_coupon
from src.controllers.admin_coupons_controller import (
    admin_create_coupon as admin_create_coupon_controller,
    admin_list_coupons as admin_list_coupons_controller,
    admin_update_coupon as admin_update_coupon_controller,
)
from src.controllers.admin_gift_cards_controller import create_gift_card as admin_create_gift_card_controller
from src.controllers.admin_products_controller import generate_stock_movement_id, get_stock_movement_status
from src.controllers.credit_controller import get_credit, redeem_gift_card, checkout_credit
from src.controllers.op_sessions_controller import list_sessions, manage_session
from src import proxy as proxy_module
from src import opkey_middleware
from src.chatbot import service as chatbot_answer_service
from src.controllers.products_controller import product_categories as product_categories_controller
from src.controllers.admin_audit_controller import admin_list_audit as admin_list_audit_controller
from src.controllers.admin_sales_controller import (
    get_admin_sales_categories as admin_sales_categories_controller,
    get_admin_sales_metrics as admin_sales_metrics_controller,
)
from src.controllers.admin_users_controller import (
    list_users as admin_users_list_controller,
    update_user_privilege as admin_user_privilege_update_controller,
)
from src.services import list_available_coupons, list_product_categories
from src import catalog_cache
from src.chatbot import rate_limit as chatbot_rate_limit
from flask import jsonify

app = Flask(__name__)
_MAX_CATALOG_EVENT_BODY_BYTES = 1024
_chatbot_answer_service = None
_chatbot_answer_service_lock = threading.Lock()


def _get_chatbot_answer_service():
    global _chatbot_answer_service
    if _chatbot_answer_service is None:
        with _chatbot_answer_service_lock:
            if _chatbot_answer_service is None:
                cache_directory = os.getenv("CHAT_CHROMA_DIR") or str(
                    Path.home()
                    / ".cache"
                    / "bgg-shop-bff"
                    / "approved-faq-chroma"
                )
                _chatbot_answer_service = (
                    chatbot_answer_service.create_local_chatbot_service(
                        Path(__file__).resolve().parent / "knowledge",
                        persist_directory=cache_directory,
                    )
                )
    return _chatbot_answer_service


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
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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
    if request.path not in _CREDIT_PATHS and request.path not in (
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    ):
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


@app.after_request
def _no_store_current_user_response(response):
    if request.path == "/api/v1/auth/me":
        response.headers["Cache-Control"] = "no-store"
    return response


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
app.config["CHAT_SESSION_COOKIE_SECURE"] = not development
app._chat_rate_limiter = chatbot_rate_limit.check_request_limit


@app.route("/health", methods=["GET"])
def health():
    return health_controller()


@app.route("/api/v1/_debug/headers", methods=["POST"])
def debug_headers():
    return ('', 204)


@app.route("/api/v1/products", methods=["GET"])
def products():
    return products_controller(list_products)


@app.route("/api/v1/product-categories", methods=["GET"])
def product_categories():
    return product_categories_controller(list_product_categories)


@app.route("/api/v1/chat/conversations", methods=["POST"])
def chat_create_conversation():
    return create_chat_conversation_controller(
        create_chat_conversation,
        app._chat_rate_limiter,
        app.config["CHAT_SESSION_COOKIE_SECURE"],
    )


@app.route("/api/v1/chat/conversations/<conversation_id>", methods=["GET"])
def chat_get_conversation(conversation_id):
    return get_chat_conversation_controller(
        conversation_id,
        app._chat_rate_limiter,
    )


@app.route("/api/v1/chat/conversations/<conversation_id>", methods=["DELETE"])
def chat_delete_conversation(conversation_id):
    return delete_chat_conversation_controller(
        conversation_id,
        app._chat_rate_limiter,
    )


@app.route(
    "/api/v1/chat/conversations/<conversation_id>/messages",
    methods=["POST"],
)
def chat_send_message(conversation_id):
    return send_chat_message_controller(
        conversation_id,
        record_chat_exchange,
        app._chat_rate_limiter,
        _get_chatbot_answer_service,
    )


@app.route("/api/v1/coupons", methods=["GET"])
def available_coupons():
    return list_available_coupons_controller(list_available_coupons)


@app.route("/api/v1/games/<slug>", methods=["GET"])
def game_detail(slug):
    return product_detail_controller(slug, get_product_detail)


@app.route("/internal/v1/catalog-events", methods=["POST"])
def receive_catalog_event():
    request.max_content_length = _MAX_CATALOG_EVENT_BODY_BYTES
    if (
        request.content_length is not None
        and request.content_length > _MAX_CATALOG_EVENT_BODY_BYTES
    ):
        return jsonify({"error": "invalid event"}), 413

    secret = os.getenv("CATALOG_EVENTS_HMAC_SECRET") or os.getenv(
        "OPKEY_INTERNAL_SECRET", ""
    )
    if not secret:
        return jsonify({"error": "event processing unavailable"}), 503

    try:
        body = request.get_data(cache=True)
    except RequestEntityTooLarge:
        return jsonify({"error": "invalid event"}), 413
    supplied_signature = request.headers.get("X-Catalog-Event-Signature", "")
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    if (
        len(supplied_signature) != 71
        or not supplied_signature.startswith("sha256=")
        or any(character not in "0123456789abcdef" for character in supplied_signature[7:])
    ):
        return jsonify({"error": "unauthorized"}), 401
    if not hmac.compare_digest(expected_signature, supplied_signature):
        return jsonify({"error": "unauthorized"}), 401

    if request.mimetype != "application/json":
        return jsonify({"error": "invalid event"}), 400
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"error": "invalid event"}), 400
    expected_fields = {
        "event_id",
        "event_type",
        "occurred_at",
        "aggregate_type",
        "aggregate_id",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        return jsonify({"error": "invalid event"}), 400

    event_type = payload.get("event_type")
    if event_type not in {
        "product.changed",
        "stock.changed",
        "promotion.changed",
    }:
        return jsonify({"error": "invalid event"}), 400
    expected_aggregate = event_type.removesuffix(".changed")
    if payload.get("aggregate_type") != expected_aggregate:
        return jsonify({"error": "invalid event"}), 400
    try:
        uuid.UUID(payload["event_id"])
        occurred_at = payload["occurred_at"]
        if not isinstance(occurred_at, str):
            raise ValueError
        if not (occurred_at.endswith("Z") or occurred_at.endswith("+00:00")):
            raise ValueError
        parsed_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if parsed_at.utcoffset() is None or parsed_at.utcoffset().total_seconds() != 0:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        return jsonify({"error": "invalid event"}), 400
    aggregate_id = payload["aggregate_id"]
    if (
        not isinstance(aggregate_id, str)
        or not aggregate_id.strip()
        or len(aggregate_id) > 128
    ):
        return jsonify({"error": "invalid event"}), 400

    try:
        catalog_cache.invalidate_catalog_cache(payload["event_id"])
    except Exception:
        app.logger.error("Catalog cache invalidation failed.")
        return jsonify({"error": "event processing unavailable"}), 503
    return "", 204


@app.route("/api/v1/games/<slug>/reviews", methods=["POST"])
def game_review(slug):
    return create_review_controller(slug, create_review)


@app.route("/api/v1/cart", methods=["GET"])
def cart():
    return read_cart_controller(get_cart)


@app.route("/api/v1/cart/coupons/preview", methods=["POST"])
def preview_cart_coupon():
    return preview_current_cart_coupon()


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
    payload = request.get_json(silent=True)
    if isinstance(payload, dict) and "coupon_code" in payload:
        from flask import g

        g.checkout_coupon_code = payload.pop("coupon_code")
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


@app.route("/api/v1/auth/me", methods=["GET"])
def auth_current_user():
    return auth_current_user_controller(proxy_module.get_current_user_capabilities)


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


@app.route("/api/v1/auth/logout", methods=["POST"])
def logout():
    op_key = request.headers.get("X-Op-Key")
    if op_key:
        try:
            proxy_module.revoke_operation_key(op_key)
        except proxy_module.UpstreamError:
            response = app.make_response(({"error": "Operation key revocation could not be confirmed"}, 502))
            response.headers["Cache-Control"] = "no-store"
            return response
    response = app.make_response(("", 204))
    response.delete_cookie('refresh_token', path='/', secure=app.config.get('CART_COOKIE_SECURE', True), httponly=True, samesite='Strict')
    response.headers["Cache-Control"] = "no-store"
    return response


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
@app.route("/api/v1/admin/users", methods=["GET"])
def admin_users_list():
    return admin_users_list_controller()


@app.route("/api/v1/admin/users/<user_id>/privileges", methods=["PATCH"])
def admin_user_privilege_update(user_id):
    return admin_user_privilege_update_controller(user_id)


@app.route("/api/v1/admin/reviews", methods=["GET"])
def admin_reviews_list():
    return admin_list_reviews_controller(admin_list_reviews)


@app.route("/api/v1/admin/reviews/<int:review_id>/actions", methods=["POST"])
def admin_reviews_moderate(review_id):
    return admin_moderate_review_controller(review_id, admin_moderate_review)


@app.route("/api/v1/admin/op-sessions", methods=["GET"])
def admin_op_sessions():
    return list_sessions()


@app.route("/api/v1/admin/op-sessions/<session_id>/revoke", methods=["POST"])
def admin_op_session_revoke(session_id):
    return manage_session(session_id, "REVOKE")


@app.route("/api/v1/admin/op-sessions/<session_id>/expire", methods=["POST"])
def admin_op_session_expire(session_id):
    return manage_session(session_id, "EXPIRE")


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


@app.route("/api/v1/admin/products/<product_id>/stock", methods=["POST"])
def admin_products_adjust_stock(product_id):
    return admin_adjust_variant_stock(product_id)


@app.route("/api/v1/admin/stock-movement-ids", methods=["POST"])
def admin_stock_movement_id_generate():
    return generate_stock_movement_id()


@app.route("/api/v1/admin/stock-movements/<movement_id>", methods=["GET"])
def admin_stock_movement_status(movement_id):
    return get_stock_movement_status(movement_id)


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


# Admin audit
@app.route("/api/v1/admin/audit", methods=["GET"])
def admin_audit_list():
    return admin_list_audit_controller()


@app.route("/api/v1/admin/sales-metrics", methods=["GET"])
def admin_sales_metrics():
    return admin_sales_metrics_controller()


@app.route("/api/v1/admin/sales-metrics/categories", methods=["GET"])
def admin_sales_categories():
    return admin_sales_categories_controller()


# Admin coupons
@app.route("/api/v1/admin/coupons", methods=["GET"])
def admin_coupons_list():
    return admin_list_coupons_controller()


@app.route("/api/v1/admin/coupons", methods=["POST"])
def admin_coupons_create():
    return admin_create_coupon_controller()


@app.route("/api/v1/admin/coupons/<int:coupon_id>", methods=["PATCH"])
def admin_coupons_update(coupon_id):
    return admin_update_coupon_controller(coupon_id)


@app.route("/api/v1/admin/coupons/<code>/apply", methods=["POST"])
def admin_coupons_apply(code):
    return admin_apply_coupon_preview_controller(code)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
