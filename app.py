# bgg-shop-bff/app.py
from flask import Flask, jsonify, request
from src.proxy import UpstreamError, list_products

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/api/v1/products", methods=["GET"])
def products():
    try:
        page = request.args.get("page", 1)
        page_size = request.args.get("page_size", 20)
        return jsonify(list_products(page, page_size)), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        return jsonify({"error": "upstream GraphQL request failed", "detail": str(exc)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)