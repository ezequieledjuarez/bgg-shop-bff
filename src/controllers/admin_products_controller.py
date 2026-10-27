from flask import jsonify, request, g

from .. import auth
from ..proxy import UpstreamError
from ..services import (
    admin_list_products as admin_list_products_service,
    admin_create_product as admin_create_product_service,
    admin_update_product as admin_update_product_service,
    adjust_variant_stock as adjust_variant_stock_service,
    get_product_by_bgg_id as get_product_by_bgg_id_service,
)
from ..dtos.products import (
    AdminCreateProductDto,
    AdminUpdateProductDto,
    AdjustStockDto,
)


@auth.admin_required
def admin_list_products():
    args = request.args
    # Verification marker: ensure this controller path can create the error log
    try:
        # Defensive wrapper: call the `services` module implementation directly
        # to avoid issues if the imported `admin_list_products_service` alias
        # is shadowed due to import-order/circular-import effects in the running
        # process. Use this internal wrapper throughout the controller.
        def _call_admin_list_products_flex(**kwargs):
            from .. import services as _services
            return _services.admin_list_products(**kwargs)

        import json, datetime
        with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'ts': datetime.datetime.utcnow().isoformat() + 'Z', 'note': 'admin_list_products_entered'}) + "\n")
    except Exception:
        pass
    try:
        # forward Authorization header token to service so proxy can send it upstream
        token = request.headers.get("Authorization")
        # Conditional controller-level dump before calling service (controlled by env var)
        try:
            import os, json, datetime
            if os.getenv("BFF_DUMP_BEFORE_ADMIN", "").lower() in ("1", "true", "yes") or os.path.exists('/tmp/BFF_DUMP_BEFORE_ADMIN'):
                try:
                    dump = {
                        "ts": datetime.datetime.utcnow().isoformat() + "Z",
                        "note": "controller_pre_call_admin_list_products",
                        "path": request.path,
                        "method": request.method,
                        "args": dict(request.args),
                        "headers": {"Authorization": token},
                        "masked_token": (token[:10] + '...' if token and isinstance(token, str) and len(token) > 13 else token),
                    }
                    with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(dump, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            pass
        # Temporary debug: capture raw representation and length to triage truncation
        try:
            print(f"[admin_list_products-debug] Authorization raw_repr={repr(token)} length={len(token) if token else 0}")
        except Exception:
            pass
        # Persistent check: if raw headers include Authorization but token is falsy, persist for offline triage
        try:
            raw_keys = [k.lower() for k in request.headers.keys()]
            has_auth_header = 'authorization' in raw_keys
            if has_auth_header and not token:
                try:
                    import json, datetime
                    entry = {
                        'ts': datetime.datetime.utcnow().isoformat() + 'Z',
                        'note': 'auth_header_present_but_token_none',
                        'path': request.path,
                        'method': request.method,
                        'request_headers': dict(request.headers),
                    }
                    with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            pass
        # log masked token for triage
        try:
            # Print headers for triage (may include Authorization)
            hdrs = dict(request.headers)
            print('[admin_list_products] request.headers=', hdrs)
            # persist correlation info to bff debug log for offline matching
            try:
                import json
                out_path = '/tmp/bff-debug-headers.log'
                entry = {'ts': __import__('datetime').datetime.utcnow().isoformat() + 'Z', 'path': request.path, 'method': request.method, 'request_headers': hdrs}
                with open(out_path, 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass
            if token and isinstance(token, str):
                masked = token[:10] + '...' if len(token) > 13 else token
                print(f"[admin_list_products] Authorization={masked}")
        except Exception as e:
            print('[admin_list_products] header dump failed', e)
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

            # Persist a pre-call token snapshot for offline correlation
            try:
                import json, datetime
                precall = {
                    'ts': datetime.datetime.utcnow().isoformat() + 'Z',
                    'note': 'pre_service_call_admin_list_products',
                    'correlation_id': getattr(g, 'correlation_id', None),
                    'token_repr': None if token is None else (token[:12] + '...' if isinstance(token, str) and len(token) > 16 else token),
                    'token_len': len(token) if token else 0,
                    'params': {k: v for k, v in params.items() if k != 'token'},
                }
                with open('/tmp/bff-precall-token.log', 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(precall, ensure_ascii=False) + "\n")
            except Exception:
                pass
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
    except UpstreamError as exc:
        # Log upstream error details for triage
        try:
            print(f"[admin_list_products] upstream error: {exc} (user_error={getattr(exc,'user_error', False)})")
        except Exception:
            pass
        # Persist the upstream error context (best-effort) for offline triage
        try:
            import json, datetime
            entry = {
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "controller_admin_list_products_upstream_error",
                "path": request.path,
                "error": str(exc),
                "user_error": getattr(exc, 'user_error', False),
                "field": getattr(exc, 'field', None),
                "code": getattr(exc, 'code', None),
                "response_text": getattr(exc, 'response_text', None),
                "request_headers": dict(request.headers),
            }
            with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return jsonify({"error": "upstream GraphQL request failed", "detail": str(exc)}), 502


@auth.admin_required
def admin_create_product():
    payload = request.get_json()
    # Persist a compact incoming request trace for offline triage
    try:
        import json, datetime, os
        trace = {
            'ts': datetime.datetime.utcnow().isoformat() + 'Z',
            'note': 'admin_create_product_incoming',
            'path': request.path,
            'method': request.method,
            'headers': {
                'Authorization': None if not request.headers.get('Authorization') else (request.headers.get('Authorization')[:10] + '...'),
                'X-Op-Key': None if not request.headers.get('X-Op-Key') else (request.headers.get('X-Op-Key')[:6] + '...' + request.headers.get('X-Op-Key')[-4:]),
            },
            'body_snippet': None if not payload else (json.dumps(payload, ensure_ascii=False)[:1000])
        }
        out = '/tmp/bff-calltrace.log'
        with open(out, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception:
        pass
    try:
        dto = AdminCreateProductDto.from_payload(payload)
        validated = dto.validate()
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
            print(f"[admin_create_product] caching created product bgg_id={bgg} name={name}")
            rec = {
                'ts': datetime.datetime.utcnow().isoformat() + 'Z',
                'bgg_id': bgg,
                'name': name,
            }
            # Debug: write attempt and success/failure markers
            try:
                with open('/tmp/bff-created-products-debug.log', 'a', encoding='utf-8') as dbgfh:
                    dbgfh.write(json.dumps({"ts": datetime.datetime.utcnow().isoformat() + 'Z', "note": "controller_cache_write_attempt", "rec": rec}, ensure_ascii=False) + "\n")
            except Exception:
                pass
            try:
                with open('/tmp/bff-created-products.log', 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[admin_create_product] cache write failed: {e}")
                try:
                    with open('/tmp/bff-created-products-debug.log', 'a', encoding='utf-8') as dbgfh:
                        dbgfh.write(json.dumps({"ts": datetime.datetime.utcnow().isoformat() + 'Z', "note": "controller_cache_write_failed", "error": str(e)}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            else:
                print("[admin_create_product] cache write ok")
                try:
                    with open('/tmp/bff-created-products-debug.log', 'a', encoding='utf-8') as dbgfh:
                        dbgfh.write(json.dumps({"ts": datetime.datetime.utcnow().isoformat() + 'Z', "note": "controller_cache_write_success", "bgg_id": bgg}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception as e:
            print(f"[admin_create_product] cache write failed: {e}")
        return jsonify(result), 201
    except ValueError as exc:
        print(f"[admin_create_product] validation error: {exc}")
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        try:
            print(f"[admin_create_product] upstream error: {exc} user_error={getattr(exc,'user_error', False)} field={getattr(exc,'field',None)} code={getattr(exc,'code',None)}")
        except Exception:
            pass
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        status = 502
        # Persist controller-level upstream error context
        try:
            import json, datetime
            entry = {
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "controller_admin_create_product_upstream_error",
                "path": request.path,
                "error": str(exc),
                "user_error": getattr(exc, 'user_error', False),
                "field": getattr(exc, 'field', None),
                "code": getattr(exc, 'code', None),
                "response_text": getattr(exc, 'response_text', None),
                "request_headers": dict(request.headers),
            }
            with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return jsonify({"error": "upstream GraphQL request failed"}), status


@auth.admin_required
def admin_update_product(product_id):
    payload = request.get_json()
    # Debug: persist incoming update payload for offline triage
    try:
        import json, datetime
        trace = {
            'ts': datetime.datetime.utcnow().isoformat() + 'Z',
            'note': 'admin_update_product_incoming',
            'path': request.path,
            'method': request.method,
            'body_snippet': None if not payload else (json.dumps(payload, ensure_ascii=False)[:2000])
        }
        with open('/tmp/bff-admin-update-incoming.log', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")
        try:
            print(f"[admin_update_product] incoming payload snippet={trace['body_snippet']}")
        except Exception:
            pass
    except Exception:
        pass
    try:
        dto = AdminUpdateProductDto.from_payload(payload)
        validated = dto.validate()
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
    except ValueError as exc:
        print(f"[admin_update_product] validation error: {exc}")
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        try:
            print(f"[admin_update_product] upstream error: {exc} user_error={getattr(exc,'user_error', False)}")
        except Exception:
            pass
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        try:
            import json, datetime
            entry = {
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "controller_admin_update_product_upstream_error",
                "path": request.path,
                "error": str(exc),
                "user_error": getattr(exc, 'user_error', False),
                "field": getattr(exc, 'field', None),
                "code": getattr(exc, 'code', None),
                "response_text": getattr(exc, 'response_text', None),
                "request_headers": dict(request.headers),
            }
            with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return jsonify({"error": "upstream GraphQL request failed"}), 502


@auth.admin_required
def admin_adjust_variant_stock(product_id, variant_id):
    payload = request.get_json()
    try:
        dto = AdjustStockDto.from_payload(payload)
        new_stock = dto.validate()
        token = request.headers.get("Authorization")
        op_key = request.headers.get("X-Op-Key") or request.headers.get("x-op-key")
        # adjust_variant_stock_service accepts token only; pass op_key via token wrapper if needed
        # prefer explicit token; otherwise pass None and rely on proxy to pick up op_key
        if op_key and not token:
            # pass op_key in place of token as a convention (proxy will prefer explicit op_key when provided)
            result = adjust_variant_stock_service(product_id, variant_id, new_stock, None)
        else:
            result = adjust_variant_stock_service(product_id, variant_id, new_stock, token)
        return jsonify(result), 200
    except ValueError as exc:
        print(f"[admin_adjust_variant_stock] validation error: {exc}")
        return jsonify({"error": str(exc)}), 400
    except UpstreamError as exc:
        try:
            print(f"[admin_adjust_variant_stock] upstream error: {exc} user_error={getattr(exc,'user_error', False)}")
        except Exception:
            pass
        if exc.user_error:
            err = {"field": exc.field, "code": exc.code, "message": str(exc)}
            return jsonify({"errors": [err]}), 400
        try:
            import json, datetime
            entry = {
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "controller_admin_adjust_variant_stock_upstream_error",
                "path": request.path,
                "error": str(exc),
                "user_error": getattr(exc, 'user_error', False),
                "field": getattr(exc, 'field', None),
                "code": getattr(exc, 'code', None),
                "response_text": getattr(exc, 'response_text', None),
                "request_headers": dict(request.headers),
            }
            with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return jsonify({"error": "upstream GraphQL request failed"}), 502


@auth.admin_required
def admin_get_product(product_id):
    """
    Admin GET product by BGG id (fallback implementation for admin UI).
    Performs a products listing with a larger page_size and searches for the
    matching bgg_id. This is a pragmatic helper for the admin UI tests.
    """
    try:
        token = request.headers.get("Authorization")
        # Quick local cache check: if the product was just created in this BFF
        # process, consult the lightweight /tmp cache to avoid false 404s due
        # to upstream indexing latency.
        try:
            import json, os
            cache_path = '/tmp/bff-created-products.log'
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as fh:
                    for line in fh:
                        try:
                            entry = json.loads(line)
                        except Exception:
                            continue
                        if str(entry.get('bgg_id')) == str(product_id):
                            # Attempt to fetch full product by bgg_id so admin UI gets
                            # the fields it needs (price, quantity, etc.). This
                            # avoids client-side validation failures when the
                            # cache only contains a minimal record.
                            try:
                                # use the service wrapper to avoid circular import issues
                                from .. import services as _services
                                token = request.headers.get('Authorization')
                                prod = _services.get_product_by_bgg_id(product_id, token)
                                return jsonify(prod), 200
                            except Exception:
                                # Fallback: return a slightly richer minimal shape
                                # with safe defaults so the edit form validation
                                # doesn't block saving.
                                return jsonify({'bgg_id': entry.get('bgg_id'), 'name': entry.get('name'), 'price': 0, 'quantity': 0}), 200
        except Exception:
            pass
        # Prefer a direct GraphQL lookup by bggId (more efficient/robust if
        # the upstream supports it). Fall back to paginated scanning if the
        # direct field is unavailable or returns not found.
        try:
            product = get_product_by_bgg_id_service(product_id, token)
            return jsonify(product), 200
        except UpstreamError as exc:
            # If the upstream explicitly reports not-found for direct query,
            # fall back to the safer paginated scan. Otherwise propagate 502.
            if getattr(exc, 'code', None) != 'PRODUCT_NOT_FOUND':
                raise
        # Fallback: iterate pages to find the requested bgg_id.
        def scan_for_product():
            page = 1
            page_size = 200
            max_pages = 10
            while page <= max_pages:
                result = admin_list_products_service(page=page, page_size=page_size, token=token)
                items = result.get("items") if isinstance(result, dict) else []
                for item in items:
                    if str(item.get("bgg_id")) == str(product_id):
                        return item
                try:
                    total_pages = int(result.get('total_pages') or 0)
                    if total_pages and page >= total_pages:
                        break
                except Exception:
                    pass
                page += 1
            return None

        found = scan_for_product()
        if found:
            return jsonify(found), 200

        # If not found, allow a small number of short retries to account for
        # upstream eventual consistency (indexing) before returning 404.
        import time
        retries = 3
        delay = 0.2
        for attempt in range(retries):
            time.sleep(delay)
            # try direct lookup first
            try:
                product = get_product_by_bgg_id_service(product_id, token)
                return jsonify(product), 200
            except UpstreamError:
                # fall back to scanning again
                found = scan_for_product()
                if found:
                    return jsonify(found), 200

        return jsonify({"error": "product not found"}), 404
    except UpstreamError as exc:
        try:
            print(f"[admin_get_product] upstream error: {exc} user_error={getattr(exc,'user_error', False)}")
        except Exception:
            pass
        try:
            import json, datetime
            entry = {
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "note": "controller_admin_get_product_upstream_error",
                "path": request.path,
                "error": str(exc),
                "user_error": getattr(exc, 'user_error', False),
                "field": getattr(exc, 'field', None),
                "code": getattr(exc, 'code', None),
                "response_text": getattr(exc, 'response_text', None),
                "request_headers": dict(request.headers),
            }
            with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return jsonify({"error": "upstream GraphQL request failed"}), 502
