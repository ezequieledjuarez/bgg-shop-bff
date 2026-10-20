from flask import Response, jsonify, request, stream_with_context

from ..dtos.orders import CheckoutRequestDto, ConfirmPaymentRequestDto, order_uuid
from ..proxy import UpstreamError


_ERROR_STATUS = {
    "UNAUTHENTICATED": 401,
    "ORDER_NOT_FOUND": 404,
    "PAYMENTS_DISABLED": 503,
    "PAYMENT_INITIALIZATION_FAILED": 502,
    "INVALID_SHIPPING_MODE": 400,
    "ADDRESS_REQUIRED": 400,
    "EMPTY_CART": 422,
    "INSUFFICIENT_STOCK": 409,
    "ORDER_NOT_PAYABLE": 422,
    "PAYMENT_NOT_VERIFIED": 422,
    "PAYMENT_ORDER_MISMATCH": 422,
    "PAYMENT_AMOUNT_MISMATCH": 422,
}


def _unauthorized():
    return jsonify({"errors": [{"code": "UNAUTHENTICATED", "message": "Authentication is required."}]}), 401


def _authorized_token():
    token = request.headers.get("Authorization")
    return token if token else None


def _validation_error(exc):
    return jsonify({"errors": [{"code": "INVALID", "message": str(exc)}]}), 400


def _upstream_error(exc):
    status = _ERROR_STATUS.get(exc.code)
    if status is None:
        if exc.user_error:
            status = 400
        else:
            return jsonify({"error": "upstream GraphQL request failed"}), 502
    error = {"code": exc.code, "message": str(exc)}
    if exc.field is not None:
        error["field"] = exc.field
    return jsonify({"errors": [error]}), status


def _call(operation, *args):
    try:
        return operation(*args)
    except UpstreamError as exc:
        return _upstream_error(exc)


def checkout(service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    try:
        payload = CheckoutRequestDto.from_payload(request.get_json(silent=True))
    except ValueError as exc:
        return _validation_error(exc)
    result = _call(service, *payload.to_core(), token)
    if isinstance(result, tuple):
        return result
    return jsonify({"order": result["order"], "init_point": result["init_point"]}), 200


def retry_payment(order_id, service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    try:
        identifier = order_uuid(order_id)
    except ValueError as exc:
        return _validation_error(exc)
    result = _call(service, identifier, token)
    if isinstance(result, tuple):
        return result
    return jsonify({"order": result["order"], "init_point": result["init_point"]}), 200


def confirm_payment(service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    try:
        payload = ConfirmPaymentRequestDto.from_payload(request.get_json(silent=True))
    except ValueError as exc:
        return _validation_error(exc)
    result = _call(service, payload.order_id, payload.payment_id, token)
    if isinstance(result, tuple):
        return result
    return jsonify({"order": result["order"]}), 200


def list_orders(service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    result = _call(service, token)
    if isinstance(result, tuple):
        return result
    return jsonify({"orders": result}), 200


def order_detail(order_id, service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    try:
        identifier = order_uuid(order_id)
    except ValueError as exc:
        return _validation_error(exc)
    result = _call(service, identifier, token)
    if isinstance(result, tuple):
        return result
    return jsonify({"order": result}), 200


def order_invoice(order_id, service):
    token = _authorized_token()
    if not token:
        return _unauthorized()
    try:
        identifier = order_uuid(order_id)
    except ValueError as exc:
        return _validation_error(exc)
    try:
        upstream = service(identifier, token)
    except UpstreamError as exc:
        return _upstream_error(exc)
    headers = {"Content-Type": "application/pdf"}
    for name in ("Content-Type", "Content-Disposition"):
        if upstream.headers.get(name):
            headers[name] = upstream.headers[name]
    if upstream.status_code == 404:
        body = upstream.content
        upstream.close()
        return Response(body, status=404, headers=headers)
    if upstream.status_code != 200:
        upstream.close()
        return jsonify({"error": "upstream invoice request failed"}), 502

    def generate():
        try:
            yield from upstream.iter_content(chunk_size=8192)
        finally:
            upstream.close()

    return Response(stream_with_context(generate()), status=200, headers=headers)
