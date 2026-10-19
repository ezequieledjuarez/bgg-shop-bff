from flask import Flask
from flask_cors import CORS
from src.controllers import (
    auth_request,
    health as health_controller,
    products as products_controller,
)
from src.services import authenticate_account, list_products, register_account

app = Flask(__name__)
allowed_origins = ("http://localhost:3000", "http://127.0.0.1:3000")
CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.route("/health", methods=["GET"])
def health():
    return health_controller()


@app.route("/api/v1/products", methods=["GET"])
def products():
    return products_controller(list_products)


@app.route("/api/v1/auth/register", methods=["POST"])
def register():
    return auth_request(register_account, 201)


@app.route("/api/v1/auth/login", methods=["POST"])
def login():
    return auth_request(authenticate_account, 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)