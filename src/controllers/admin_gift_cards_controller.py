import os
import re
import uuid
from decimal import Decimal, InvalidOperation

import requests
from flask import jsonify, request


MUTATION = """
mutation IssueGiftCard($amount: String!) {
  createGiftCard(amount: $amount) {
    giftCard { id code amount currency }
    userErrors { code message }
  }
}
"""


def _response(payload, status):
    result = jsonify(payload)
    result.headers["Cache-Control"] = "no-store"
    return result, status


def create_gift_card():
    token = request.headers.get("Authorization", "")
    if not re.fullmatch(r"Bearer\s+\S+", token, flags=re.IGNORECASE):
        return _response({"error": "Authentication required"}, 401)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"amount"}:
        return _response({"error": "Invalid request"}, 400)
    amount = payload["amount"]
    if not isinstance(amount, str) or not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,2})?", amount) or Decimal(amount) <= 0:
        return _response({"error": "Invalid amount"}, 400)
    try:
        upstream = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", "http://localhost:8000/graphql/"),
            json={"query": MUTATION, "variables": {"amount": amount}},
            headers={"Authorization": token},
            timeout=10,
        )
        upstream.raise_for_status()
        data = upstream.json()
        result = data["data"]["createGiftCard"]
        errors = result["userErrors"]
        if errors:
            code = errors[0].get("code")
            status = {"UNAUTHENTICATED": 401, "FORBIDDEN": 403, "INVALID_AMOUNT": 400}.get(code, 502)
            return _response({"error": "Gift card could not be issued"}, status)
        card = result["giftCard"]
        uuid.UUID(card["id"])
        if not re.fullmatch(r"[0-9a-f]{64}", card["code"]) or card["currency"] != "ARS" or Decimal(card["amount"]) != Decimal(amount):
            raise ValueError("Invalid response")
        return _response({key: card[key] for key in ("id", "code", "amount", "currency")}, 201)
    except (requests.RequestException, ValueError, InvalidOperation, KeyError, TypeError, IndexError, AttributeError):
        return _response({"error": "Gift card issuance could not be confirmed"}, 502)