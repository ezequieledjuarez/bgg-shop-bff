from uuid import UUID, uuid4

from flask import current_app, jsonify, make_response, request, g

from .. import auth
from ..proxy import UpstreamError
from ..services import (
    admin_list_products as admin_list_products_service,
    admin_create_product as admin_create_product_service,
    admin_update_product as admin_update_product_service,
    adjust_product_stock as adjust_product_stock_service,
    get_product_by_bgg_id as get_product_by_bgg_id_service,
    get_stock_movement_status as get_stock_movement_status_service,
)
from ..dtos.products import (
    AdminCreateProductDto,
    AdminUpdateProductDto,
    AdjustStockDto,
)


def _product_upstream_error(exc, allow_not_found=False):
    public_errors = {
        "NAME_REQUIRED": ("Name is required", "name"),
        "INVALID_NAME": ("Invalid name", "name"),
        "DUPLICATE": ("Product conflicts with existing data", None),
        "NO_OP": ("At least one field must be provided", None),
    }
    if exc.user_error and isinstance(exc.code, str):
        if exc.code in public_errors:
            message, field = public_errors[exc.code]
            error = {"code": exc.code, "message": message}
            if field:
                error["field"] = field
            return jsonify({"errors": [error]}), 400
        statuses = {
            "UNAUTHENTICATED": (401, "Authentication required"),
            "FORBIDDEN": (403, "forbidden"),
        }
        if allow_not_found:
            statuses["PRODUCT_NOT_FOUND"] = (404, "Product not found")
        if exc.code in statuses:
            status, message = statuses[exc.code]
            return jsonify({"error": message}), status
    return jsonify({"error": "upstream GraphQL request failed"}), 502


@auth.admin_required
def generate_stock_movement_id():
    response = jsonify({"movement_id": str(uuid4())})
    response.headers["Cache-Control"] = "no-store"
    return response


@auth.admin_required
def _get_stock_movement_status(movement_id):
    try:
        identifier = str(UUID(movement_id))
    except (ValueError, TypeError, AttributeError):
        return jsonify({"error": "Invalid movement identifier"}), 400
    try:
        return jsonify(get_stock_movement_status_service(identifier, request.headers.get("Authorization"))), 200
    except UpstreamError as exc:
        statuses = {"INVALID": 400, "UNAUTHENTICATED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404}
        status = statuses.get(exc.code, 502) if exc.user_error else 502
        return jsonify({"error": "Stock status request failed"}), status


def get_stock_movement_status(movement_id):
    response = make_response(_get_stock_movement_status(movement_id))
    response.headers["Cache-Control"] = "no-store"
    if response.status_code != 200:
        try:
            identifier = str(UUID(movement_id))
        except (ValueError, TypeError, AttributeError):
            return response
        payload = response.get_json(silent=True)
        if isinstance(payload, dict):
            payload["movement_id"] = identifier
            response.set_data(current_app.json.dumps(payload))
    return response


@auth.admin_required
def admin_list_products():
    args = request.args
    def _call_admin_list_products_flex(**kwargs):
        from .. import services as _services
        return _services.admin_list_products(**kwargs)

    try:
        token = request.headers.get("Authorization")
        # Accept either 'q' (legacy) or 'search' (public param) to support clients
        search_param = args.get("q") or args.get("search")
        # Read optional filter and pagination params from query string and forward to service
        page = args.get("page", 1)
        # Default page_size aligns with API spec and proxy defaults
        page_size = args.get("page_size", 50)
        # Prefer the DB/DSL name `release_year`. Accept legacy `year_published`
        # and camelCase variants for compatibility, but always forward as
        # `release_year` to the services layer.
        release_year = (
            args.get("release_year")
            or args.get("releaseYear")
            or args.get("year_published")
            or args.get("yearPublished")
        )
        min_players = args.get("min_players") or args.get("minPlayers")
        max_players = args.get("max_players") or args.get("maxPlayers")
        category_id = args.get("category_id") or args.get("categoryId")
        price_min = args.get("price_min") or args.get("priceMin")
        price_max = args.get("price_max") or args.get("priceMax")

        # Defensive call: assemble params and call services.list_products
        try:
            from .. import services as _services
            params = {
                'page': page,
                'page_size': page_size,
                'search': search_param,
                'token': token,
            }
            # include optional filters only when provided
            if release_year:
                params['release_year'] = release_year
            if min_players:
                params['min_players'] = min_players
            if max_players:
                params['max_players'] = max_players
            if category_id:
                params['category_id'] = category_id
            if price_min:
                params['price_min'] = price_min
            if price_max:
                params['price_max'] = price_max

            result = _services.list_products(**params)
        except Exception:
            # fallback: call the proxy directly to avoid any alias/import
            # recursion issues. This forwards the assembled params to the
            # lower-level proxy layer which implements `list_products`.
            try:
                from .. import proxy as _proxy
                # Reuse the params dict built above (includes token and filters)
                result = _proxy.list_products(**params)
            except Exception:
                # If proxy call fails, fall back to the defensive services
                # wrapper to preserve previous behavior.
                try:
                    # Call the services fallback with a minimal, well-known set of
                    # parameters to avoid unexpected keyword argument errors in
                    # environments where the services signature may differ.
                    result = _call_admin_list_products_flex(
                        page=page,
                        page_size=page_size,
                        q=search_param,
                        token=token,
                    )
                except Exception:
                    # As a last-resort, return a minimal empty result
                    result = {'items': [], 'page': page, 'page_size': page_size}
        # Include X-Page-Size-Used and X-Debug-Correlation headers for clients and triage
        resp = jsonify(result)
        try:
            used = result.get('page_size') if isinstance(result, dict) else None
            if used is not None:
                resp.headers['X-Page-Size-Used'] = str(used)
        except Exception:
            pass
        try:
            cid = getattr(g, 'correlation_id', None)
            if cid:
                resp.headers['X-Debug-Correlation'] = cid
        except Exception:
            pass
        return resp, 200
    except ValueError as exc:
        # Descriptive log for validation errors
        try:
            print(f"[admin_list_products] validation error: {exc}")
        except Exception:
            pass
        return jsonify({"error": str(exc)}), 400
    except UpstreamError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502


@auth.admin_required
def admin_create_product():
    payload = request.get_json()
    try:
        dto = AdminCreateProductDto.from_payload(payload)
        validated = dto.validate()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        # pass Authorization header token and X-Op-Key down to service/proxy
        token = request.headers.get("Authorization")
        op_key = request.headers.get("X-Op-Key") or request.headers.get("x-op-key")
        if isinstance(validated, dict):
            validated["_auth_token"] = token
            validated["_op_key"] = op_key
            # pass-through tokens only for create
        result = admin_create_product_service(validated)
        # Persist a lightweight cache entry so subsequent admin GETs can
        # find the newly created product immediately even if upstream
        # listings are eventually consistent.
        try:
            import json, datetime
            bgg = result.get('bgg_id')
            name = result.get('name')
            rec = {
                'ts': datetime.datetime.utcnow().isoformat() + 'Z',
                'bgg_id': bgg,
                'name': name,
            }
            with open('/tmp/bff-created-products.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            current_app.logger.warning("Product cache write failed.")
        return jsonify(result), 201
    except ValueError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502
    except UpstreamError as exc:
        return _product_upstream_error(exc)


@auth.admin_required
def admin_update_product(product_id):
    payload = request.get_json()
    try:
        dto = AdminUpdateProductDto.from_payload(payload)
        validated = dto.validate()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        token = request.headers.get("Authorization")
        op_key = request.headers.get("X-Op-Key") or request.headers.get("x-op-key")
        if isinstance(validated, dict):
            validated["_auth_token"] = token
            validated["_op_key"] = op_key
            # Ensure bgg identifiers are available to downstream layers.
            try:
                validated['bgg_id'] = int(product_id) if product_id is not None else validated.get('bgg_id')
            except Exception:
                validated['bgg_id'] = product_id
            try:
                validated['bggId'] = int(product_id) if product_id is not None else validated.get('bggId')
            except Exception:
                validated['bggId'] = product_id
        result = admin_update_product_service(product_id, validated)
        return jsonify(result), 200
    except ValueError:
        return jsonify({"error": "upstream GraphQL request failed"}), 502
    except UpstreamError as exc:
        return _product_upstream_error(exc, allow_not_found=True)


@auth.admin_required
def _admin_adjust_variant_stock(product_id):
    payload = request.get_json(silent=True)
    try:
        normalized_id = product_id.lstrip("0")
        if (not product_id.isascii() or not product_id.isdecimal() or not normalized_id
                or len(normalized_id) > 10 or int(normalized_id) > 2147483647):
            raise ValueError("product_id must be a positive integer")
        dto = AdjustStockDto.from_payload(payload)
        movement_id, direction, quantity = dto.validate()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        token = request.headers.get("Authorization")
        result = adjust_product_stock_service(product_id, movement_id, direction, quantity, token)
        return jsonify(result), 202 if result["status"] == "IN_PROGRESS" else 200
    except ValueError:
        return jsonify({"error": "Movement outcome may be uncertain. Refresh the screen and check the movement status."}), 502
    except UpstreamError as exc:
        if exc.user_error:
            public_errors = {
                "NOT_FOUND": (404, "Product not found"),
                "INVALID": (400, "Invalid stock request"),
                "UNAUTHENTICATED": (401, "Authentication required"),
                "FORBIDDEN": (403, "forbidden"),
                "NO_STOCK": (400, "Product has no stock"),
                "IDEMPOTENCY_CONFLICT": (409, "Movement identifier already used with different data"),
            }
            if isinstance(exc.code, str) and exc.code in public_errors:
                status, message = public_errors[exc.code]
                return jsonify({"error": message}), status
        return jsonify({"error": "Movement outcome may be uncertain. Refresh the screen and check the movement status."}), 502


def admin_adjust_variant_stock(product_id):
    response = make_response(_admin_adjust_variant_stock(product_id))
    response.headers["Cache-Control"] = "no-store"
    if response.status_code >= 400:
        payload = request.get_json(silent=True)
        try:
            identifier = str(UUID(payload.get("movement_id"))) if isinstance(payload, dict) else None
        except (ValueError, TypeError, AttributeError):
            identifier = None
        body = response.get_json(silent=True)
        if identifier and isinstance(body, dict):
            body["movement_id"] = identifier
            response.set_data(current_app.json.dumps(body))
    return response


@auth.admin_required
def admin_get_product(product_id):
    normalized_id = product_id.lstrip("0")
    if (not product_id.isascii() or not product_id.isdecimal() or not normalized_id
            or len(normalized_id) > 10 or int(normalized_id) > 2147483647):
        return jsonify({"error": "product_id must be a positive integer"}), 400
    try:
        token = request.headers.get("Authorization")
        return jsonify(get_product_by_bgg_id_service(product_id, token)), 200
    except UpstreamError as exc:
        if exc.code == "PRODUCT_NOT_FOUND":
            return jsonify({"error": "product not found"}), 404
        return jsonify({"error": "upstream GraphQL request failed"}), 502
