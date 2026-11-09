import hashlib
import json
import logging
import os
from decimal import Decimal, InvalidOperation

import redis


logger = logging.getLogger(__name__)
_redis_client = None
_INTEGER_INPUTS = {
    "page",
    "page_size",
    "year_published",
    "min_players",
    "max_players",
    "category_id",
}
_DECIMAL_INPUTS = {"price_min", "price_max"}


def _client():
    global _redis_client
    if _redis_client is None:
        url = os.getenv("CATALOG_REDIS_URL") or os.getenv(
            "REDIS_URL", "redis://redis:6379/2"
        )
        _redis_client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _redis_client


def _normalize_inputs(inputs):
    normalized = {}
    for key, value in sorted(inputs.items()):
        if isinstance(value, str) and key in (
            _INTEGER_INPUTS | _DECIMAL_INPUTS | {"search", "publisher"}
        ):
            value = value.strip()
            if not value:
                value = None
            elif key in _INTEGER_INPUTS:
                try:
                    value = int(value)
                except ValueError:
                    pass
            elif key in _DECIMAL_INPUTS:
                try:
                    value = format(Decimal(value).normalize(), "f")
                except InvalidOperation:
                    pass
            elif key == "search":
                value = value.casefold()
        normalized[key] = value
    return normalized


def catalog_response(cache_type, inputs, loader):
    key = None
    client = None
    try:
        client = _client()
        generation = client.get("catalog:v1:generation") or "0"
        canonical = json.dumps(
            _normalize_inputs(inputs), sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key = f"catalog:v1:{generation}:{cache_type}:{digest}"
        cached = client.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        logger.warning("Catalog Redis cache unavailable; serving an uncached response.")

    result = loader()
    try:
        if client is not None and key is not None:
            ttl = max(1, int(os.getenv("CATALOG_CACHE_TTL_SECONDS", "60")))
            client.setex(key, ttl, json.dumps(result, separators=(",", ":")))
    except Exception:
        logger.warning("Catalog Redis cache unavailable; serving an uncached response.")
    return result


def invalidate_catalog_cache(_event_id):
    _client().incr("catalog:v1:generation")
