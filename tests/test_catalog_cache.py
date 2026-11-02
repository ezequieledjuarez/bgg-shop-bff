import logging
from unittest.mock import Mock

from src import catalog_cache, services


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl

    def incr(self, key):
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value


def test_catalog_cache_normalizes_query_inputs_and_uses_configurable_ttl(monkeypatch):
    cache = FakeRedis()
    monkeypatch.setattr(catalog_cache, "_redis_client", cache)
    monkeypatch.setenv("CATALOG_CACHE_TTL_SECONDS", "45")
    first_loader = lambda: {"items": ["first"]}
    second_loader = lambda: {"items": ["second"]}

    assert catalog_cache.catalog_response(
        "products", {"page": "01", "search": " Game "}, first_loader
    ) == {"items": ["first"]}
    assert catalog_cache.catalog_response(
        "products", {"search": "game", "page": 1}, second_loader
    ) == {"items": ["first"]}
    assert next(iter(cache.ttls.values())) == 45


def test_catalog_cache_defaults_to_sixty_seconds(monkeypatch):
    cache = FakeRedis()
    monkeypatch.setattr(catalog_cache, "_redis_client", cache)
    monkeypatch.delenv("CATALOG_CACHE_TTL_SECONDS", raising=False)

    catalog_cache.catalog_response("products", {}, lambda: {"items": []})

    assert next(iter(cache.ttls.values())) == 60


def test_catalog_cache_generation_invalidation_makes_prior_entries_unreachable(monkeypatch):
    cache = FakeRedis()
    monkeypatch.setattr(catalog_cache, "_redis_client", cache)
    loader = iter(({"quantity": 3}, {"quantity": 2}))

    assert catalog_cache.catalog_response(
        "game-detail", {"slug": "game"}, lambda: next(loader)
    ) == {"quantity": 3}
    catalog_cache.invalidate_catalog_cache("event-1")
    catalog_cache.invalidate_catalog_cache("event-1")
    assert catalog_cache.catalog_response(
        "game-detail", {"slug": "game"}, lambda: next(loader)
    ) == {"quantity": 2}


def test_catalog_cache_outage_does_not_break_catalog_read(monkeypatch, caplog):
    cache = FakeRedis()

    def unavailable(_key):
        raise ConnectionError("private redis connection detail")

    cache.get = unavailable
    monkeypatch.setattr(catalog_cache, "_redis_client", cache)
    with caplog.at_level(logging.WARNING, logger="src.catalog_cache"):
        result = catalog_cache.catalog_response(
            "products", {}, lambda: {"items": []}
        )

    assert result == {"items": []}
    assert "private redis connection detail" not in caplog.text
    assert "serving an uncached response" in caplog.text


def test_public_list_and_detail_services_cache_while_admin_list_does_not(monkeypatch):
    cache = FakeRedis()
    monkeypatch.setattr(catalog_cache, "_redis_client", cache)
    list_products = Mock(return_value={"items": []})
    monkeypatch.setattr(services.proxy, "list_products", list_products)
    monkeypatch.setattr(
        services.proxy, "get_product_detail", lambda _slug: {"bgg_id": 7}
    )
    services.list_products(page=1)
    services.get_product_detail("game")
    cache_keys = set(cache.values)
    services.admin_list_products(page=1)
    assert set(cache.values) == cache_keys
    assert list_products.call_count == 2
    assert "catalog:v1:generation" not in cache_keys
    assert any(":products:" in key for key in cache_keys)
    assert any(":game-detail:" in key for key in cache_keys)
