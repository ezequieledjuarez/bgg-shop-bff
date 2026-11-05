from unittest.mock import patch

import pytest

from app import app
from src.proxy import UpstreamError

METRICS_URL = "/api/v1/admin/sales-metrics"
CATEGORIES_URL = f"{METRICS_URL}/categories"
AUTH = {"Authorization": "Bearer synthetic-test-token"}
METRICS_PAYLOAD = {
    "data": {
        "adminSalesMetrics": {
            "revenueTotal": "0.00",
            "ordersCount": 0,
            "topProducts": [],
            "ordersByDispatchStatus": [],
            "ordersByPaymentStatus": [],
            "revenueByDay": [],
        }
    }
}


def _identity(is_staff=False, is_superuser=False):
    return {
        "data": {
            "me": {
                "id": "1",
                "email": "admin@example.test",
                "isStaff": is_staff,
                "isSuperuser": is_superuser,
            }
        }
    }


def _get_metrics(query="", payload=METRICS_PAYLOAD):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", return_value=payload) as upstream:
        response = app.test_client().get(f"{METRICS_URL}{query}", headers=AUTH)
    return response, upstream


def _success_payload(path):
    if path == CATEGORIES_URL:
        return {"data": {"adminSalesCategories": []}}
    return METRICS_PAYLOAD


@pytest.mark.parametrize("path", [METRICS_URL, CATEGORIES_URL])
def test_sales_metrics_requires_authentication(path):
    response = app.test_client().get(path)

    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


@pytest.mark.parametrize("path", [METRICS_URL, CATEGORIES_URL])
def test_sales_metrics_rejects_authenticated_non_admin(path):
    with patch("src.proxy._graphql_request", return_value=_identity()) as upstream:
        response = app.test_client().get(path, headers=AUTH)

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"
    upstream.assert_called_once()


@pytest.mark.parametrize("path", [METRICS_URL, CATEGORIES_URL])
@pytest.mark.parametrize("identity", [_identity(is_staff=True), _identity(is_superuser=True)])
def test_sales_metrics_allows_staff_and_superuser(path, identity):
    with patch(
        "src.proxy._graphql_request",
        side_effect=[identity, _success_payload(path)],
    ) as upstream:
        response = app.test_client().get(path, headers=AUTH)

    assert response.status_code == 200
    assert upstream.call_count == 2


@pytest.mark.parametrize(
    "query,field",
    [
        ("?from=2026-01-01T00:00:00", "from"),
        ("?from=2026-01-01T00:00:00Z", "to"),
        ("?to=2026-02-01T00:00:00Z", "from"),
    ],
)
def test_sales_metrics_rejects_naive_or_unpaired_dates(query, field):
    response, upstream = _get_metrics(query)

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["field"] == field
    upstream.assert_not_called()


@pytest.mark.parametrize(
    "query",
    [
        "?from=2026-02-01T00:00:00Z&to=2026-02-01T00:00:00Z",
        "?from=2025-01-01T00:00:00Z&to=2026-01-03T00:00:00Z",
    ],
)
def test_sales_metrics_rejects_invalid_range(query):
    response, upstream = _get_metrics(query)

    assert response.status_code == 400
    upstream.assert_not_called()


def test_sales_metrics_omitted_bounds_preserve_core_default_range():
    response, upstream = _get_metrics()

    assert response.status_code == 200
    variables = upstream.call_args.args[1]
    assert variables.get("from") is None
    assert variables.get("to") is None


def test_sales_metrics_rejects_non_integer_product_id():
    response, upstream = _get_metrics("?product_id=not-an-integer")

    assert response.status_code == 400
    upstream.assert_not_called()


def test_sales_metrics_forwards_repeated_filters_as_arrays():
    response, upstream = _get_metrics(
        "?category=Family&category=Strategy&product_id=17&product_id=29"
    )

    assert response.status_code == 200
    variables = upstream.call_args.args[1]
    assert variables["categories"] == ["Family", "Strategy"]
    assert variables["productIds"] == [17, 29]


def test_sales_metrics_response_is_not_cacheable():
    response, _ = _get_metrics()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_sales_categories_response_is_not_cacheable():
    with patch("src.proxy.check_admin", return_value=True), \
            patch(
                "src.proxy._graphql_request",
                return_value={"data": {"adminSalesCategories": []}},
            ):
        response = app.test_client().get(CATEGORIES_URL, headers=AUTH)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", [METRICS_URL, CATEGORIES_URL])
def test_sales_metrics_public_errors_redact_upstream_details(path):
    token = "Bearer synthetic-sensitive-token"
    private_details = (
        "Traceback (most recent call last): https://core.internal/graphql "
        "Authorization: Bearer synthetic-sensitive-token password=synthetic-secret"
    )
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.proxy._graphql_request", side_effect=UpstreamError(private_details)):
        response = app.test_client().get(path, headers={"Authorization": token})

    body = response.get_data(as_text=True)
    assert response.status_code >= 500
    for private_value in (
        "Traceback",
        "https://core.internal/graphql",
        "synthetic-sensitive-token",
        "synthetic-secret",
    ):
        assert private_value not in body