import os
import re
import uuid

import requests
from flask import json, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wsgi import get_input_stream

from ..dtos.orders import CheckoutRequestDto
from ..proxy import DEFAULT_GRAPHQL_URL, _ORDER_FIELDS, _map_order


_BALANCE = "credit { balance currency } userErrors { code }"
_MAX_BODY_BYTES = 64 * 1024
_QUERIES = {
    "myCredit": f"query MyCredit {{ myCredit {{ {_BALANCE} }} }}",
    "redeemGiftCard": f"mutation RedeemGiftCard($input: RedeemGiftCardInput!) {{ redeemGiftCard(input: $input) {{ {_BALANCE} }} }}",
    "checkoutWithCredit": f"mutation CheckoutWithCredit($input: CheckoutWithCreditInput!) {{ checkoutWithCredit(input: $input) {{ order {{ {_ORDER_FIELDS} }} {_BALANCE} }} }}",
}
_ERRORS = {
    "UNAUTHENTICATED": (401, "Authentication required."),
    "INVALID_KEY": (400, "A valid idempotency key is required."),
    "IDEMPOTENCY_CONFLICT": (409, "The idempotency key was used for another request."),
    "INVALID_GIFT_CARD": (422, "Gift card cannot be redeemed."),
    "ADDRESS_REQUIRED": (400, "A valid shipping address is required."),
    "EMPTY_CART": (422, "The cart is empty."),
    "INSUFFICIENT_STOCK": (409, "One or more items have insufficient stock."),
    "INSUFFICIENT_CREDIT": (409, "There is insufficient credit for this order."),
    "PENDING_PAYMENT": (409, "A pending payment must be resolved before using credit."),
}


def _response(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _error(code, status, message):
    return _response({"errors": [{"code": code, "message": message}]}, status)


def _unavailable():
    return _response({"error": "Credit service unavailable"}, 502)


def _token():
    token = request.headers.get("Authorization", "")
    match = re.fullmatch(r"Bearer\s+(\S+)", token, flags=re.IGNORECASE)
    return f"Bearer {match.group(1)}" if match else None


def _body():
    if not request.is_json:
        return None
    data = get_input_stream(request.environ, max_content_length=_MAX_BODY_BYTES + 1).read()
    if len(data) > _MAX_BODY_BYTES:
        raise RequestEntityTooLarge()
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None


def _key():
    try:
        return str(uuid.UUID(request.headers.get("Idempotency-Key", "")))
    except (ValueError, AttributeError, TypeError):
        return None


def _execute(field, token, variables):
    try:
        response = requests.post(
            os.getenv("SALEOR_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
            json={"query": _QUERIES[field], "variables": variables},
            headers={"Authorization": token}, timeout=10, allow_redirects=False,
        )
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            return _unavailable()
        payload = response.json()
        if payload.get("errors"):
            return _unavailable()
        result = payload["data"][field]
        errors = result["userErrors"]
        if not isinstance(errors, list):
            return _unavailable()
        if errors:
            code = errors[0]["code"]
            if not isinstance(code, str) or code not in _ERRORS:
                return _unavailable()
            status, message = _ERRORS[code]
            public_code = "ADDRESS_REQUIRED_RECORDED" if field == "checkoutWithCredit" and code == "ADDRESS_REQUIRED" else code
            return _error(public_code, status, message)
        credit = result["credit"]
        if not isinstance(credit, dict) or not isinstance(credit.get("balance"), str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", credit["balance"]) or credit.get("currency") != "ARS":
            return _unavailable()
        credit = {"balance": credit["balance"], "currency": "ARS"}
        if field != "checkoutWithCredit":
            return _response(credit, 200)
        order = _map_order(result["order"])
        if order["status"] != "paid" or not isinstance(order["invoice"], dict):
            return _unavailable()
        return _response({"order": order, "credit": credit}, 200)
    except Exception:
        return _unavailable()


def get_credit():
    token = _token()
    if not token:
        return _error("UNAUTHENTICATED", 401, "Authentication required.")
    return _execute("myCredit", token, {})


def redeem_gift_card():
    token = _token()
    if not token:
        return _error("UNAUTHENTICATED", 401, "Authentication required.")
    key = _key()
    try:
        payload = _body()
    except RequestEntityTooLarge:
        return _error("INVALID", 400, "Invalid request.")
    if not key or not isinstance(payload, dict) or set(payload) != {"code"} or not isinstance(payload["code"], str):
        return _error("INVALID", 400, "Invalid request.")
    return _execute("redeemGiftCard", token, {"input": {"code": payload["code"], "idempotencyKey": key}})


def checkout_credit():
    token = _token()
    if not token:
        return _error("UNAUTHENTICATED", 401, "Authentication required.")
    key = _key()
    try:
        if not key:
            raise ValueError("Invalid idempotency key")
        body = _body()
        payload = CheckoutRequestDto.from_payload(body)
        if "address" in body:
            address = body["address"]
    except (ValueError, RequestEntityTooLarge):
        return _error("INVALID", 400, "Invalid request.")
    core_input = {"shippingMode": payload.shipping_mode.upper(), "idempotencyKey": key}
    if "address" in body:
        core_input["address"] = {
            ("postalCode" if name == "postal_code" else name): value
            for name, value in address.items()
        }
    return _execute("checkoutWithCredit", token, {"input": core_input})