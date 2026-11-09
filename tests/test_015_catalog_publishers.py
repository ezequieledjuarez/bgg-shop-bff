from unittest.mock import MagicMock, patch

import pytest

from app import app
from src import catalog_cache, services
from src.proxy import UpstreamError, list_products


def _page():
    return {"items": [], "page": 1, "page_size": 20, "total": 0, "total_pages": 0}


def test_products_forwards_exact_trimmed_publisher():
    with patch("app.list_products", return_value=_page()) as service:
        response = app.test_client().get(
            "/api/v1/products?publisher=%20Asmodee%20"
        )

    assert response.status_code == 200
    assert service.call_args.kwargs["publisher"] == "Asmodee"


@pytest.mark.parametrize("query", [
    "publisher=",
    "publisher=%20%20",
    "publisher=" + "x" * 251,
    "publisher=Asmodee&publisher=Other",
])
def test_products_rejects_invalid_or_repeated_publisher(query):
    with patch("app.list_products", return_value=_page()) as service:
        response = app.test_client().get(f"/api/v1/products?{query}")

    assert response.status_code == 400
    service.assert_not_called()


def test_publishers_endpoint_returns_complete_snake_case_facets():
    facets = [{"publisher": "Asmodee", "product_count": 4}]
    with patch("app.list_product_publishers", return_value=facets) as service:
        response = app.test_client().get("/api/v1/product-publishers")

    assert response.status_code == 200
    assert response.get_json() == facets
    service.assert_called_once_with()


def test_publishers_endpoint_sanitizes_upstream_failure():
    secret = "synthetic-upstream-url-and-detail"
    with patch(
        "app.list_product_publishers",
        side_effect=UpstreamError(secret),
    ):
        response = app.test_client().get("/api/v1/product-publishers")

    assert response.status_code == 502
    assert secret.encode() not in response.data
    assert response.get_json() == {"error": "upstream GraphQL request failed"}


def test_products_proxy_forwards_publisher_filter_to_core():
    response = MagicMock()
    response.json.return_value = {"data": {"products": {
        "items": [], "page": 1, "pageSize": 20, "total": 0, "totalPages": 0,
    }}}
    with patch("src.proxy.requests.post", return_value=response) as post:
        list_products(publisher="  Asmodee  ")

    payload = post.call_args.kwargs["json"]
    assert payload["variables"]["publisher"] == "Asmodee"
    assert "publisher: $publisher" in payload["query"]


def test_product_publishers_proxy_maps_and_validates_core_facets():
    from src.proxy import list_product_publishers

    with patch(
        "src.proxy._graphql_request",
        return_value={"data": {"productPublishers": [
            {"publisher": "Asmodee", "productCount": 4},
        ]}},
    ) as request:
        assert list_product_publishers() == [
            {"publisher": "Asmodee", "product_count": 4}
        ]
    assert "productPublishers" in request.call_args.args[0]


@pytest.mark.parametrize("facets", [
    None,
    "Asmodee",
    [{"publisher": "", "productCount": 2}],
    [{"publisher": " Asmodee ", "productCount": 2}],
    [{"publisher": "Asmodee", "productCount": True}],
    [{"publisher": "Asmodee", "productCount": -1}],
    [{"publisher": "Asmodee"}],
    [
        {"publisher": "Asmodee", "productCount": 2},
        {"publisher": "Asmodee", "productCount": 3},
    ],
])
def test_product_publishers_proxy_rejects_invalid_core_shapes(facets):
    from src.proxy import list_product_publishers

    with patch(
        "src.proxy._graphql_request",
        return_value={"data": {"productPublishers": facets}},
    ), pytest.raises(UpstreamError):
        list_product_publishers()


def test_publisher_filter_participates_in_catalog_cache_key(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def setex(self, key, ttl, value):
            self.values[key] = value

    cache = FakeRedis()
    monkeypatch.setattr(catalog_cache, "_redis_client", cache)
    with patch(
        "src.services.proxy.list_products",
        side_effect=lambda publisher=None, **_kwargs: {"publisher": publisher},
    ) as upstream:
        assert services.list_products(publisher="Asmodee") == {"publisher": "Asmodee"}
        assert services.list_products(publisher="Kosmos") == {"publisher": "Kosmos"}
        assert services.list_products(publisher="Asmodee") == {"publisher": "Asmodee"}

    assert upstream.call_count == 2
    assert sum(":products:" in key for key in cache.values) == 2
