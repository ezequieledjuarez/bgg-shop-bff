# bgg-shop-bff/app.py
from flask import Flask, jsonify, request
from flask_cors import CORS
from src.proxy import UpstreamError, list_products

app = Flask(__name__)
allowed_origins = ("http://localhost:3000", "http://127.0.0.1:3000")
CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    methods=["GET", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/api/v1/products", methods=["GET"])
def products():
    try:
        page = request.args.get("page", 1)
        return jsonify(list_products(
            page=request.args.get("page", 1),
            page_size=request.args.get("page_size", 20),
            search=request.args.get("search"),
            year_published=request.args.get("year_published"),
            min_players=request.args.get("min_players"),
            max_players=request.args.get("max_players"),
            category_id=request.args.get("category_id"),
            price_min=request.args.get("price_min"),
            price_max=request.args.get("price_max"),
        )), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        return jsonify({"error": "upstream GraphQL request failed", "detail": str(exc)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)