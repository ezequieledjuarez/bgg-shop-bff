import os

from flask import Flask, request
from flask_cors import CORS
from src.controllers import (
    add_cart_item as add_cart_item_controller,
    auth_request,
    create_review as create_review_controller,
    health as health_controller,
    product_detail as product_detail_controller,
    products as products_controller,
    read_cart as read_cart_controller,
    remove_cart_item as remove_cart_item_controller,
    update_cart_item as update_cart_item_controller,
)
from src.services import (
    add_to_cart,
    authenticate_account,
    create_review,
    get_cart,
    get_product_detail,
    list_products,
    register_account,
    remove_from_cart,
    update_cart_quantity,
)

app = Flask(__name__)
allowed_origins = ("http://localhost:3000", "http://127.0.0.1:3000")
CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    supports_credentials=True,
)


def _configured_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
