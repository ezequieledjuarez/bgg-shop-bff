from unittest.mock import mock_open, patch

import pytest
from flask import g

from app import app
from src import proxy, services
from src.proxy import UpstreamError


def test_admin_requires_authentication():
    client = app.test_client()
    resp = client.get("/api/v1/admin/products")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Authentication required"


def test_admin_forbidden_for_non_admin():
    client = app.test_client()
    with patch("src.proxy.check_admin", return_value=False):
        resp = client.get("/api/v1/admin/products", headers={"Authorization": "Bearer token"})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_admin_allows_admin_and_returns_list():
    client = app.test_client()
    sample = {"items": [], "page": 1}
    with patch("src.proxy.check_admin", return_value=True):
        with patch("src.services.list_products", return_value=sample):
            resp = client.get("/api/v1/admin/products", headers={"Authorization": "Bearer token"})
    assert resp.status_code == 200
    assert resp.get_json() == sample


def test_admin_auth_and_product_list_do_not_log_credentials(capsys, caplog):
    token = "Bearer synthetic-admin-secret"
    sample = {"items": [], "page": 1, "page_size": 50}
    with patch.dict("os.environ", {"BFF_DUMP_BEFORE_ADMIN": "1"}), \
            patch("src.proxy.check_admin", return_value=True), \
            patch("src.services.list_products", return_value=sample) as service, \
            patch("app._append_incoming_log"), \
            patch("app._opkey_before_request", return_value=None), \
            patch("builtins.open", create=True) as file_open:
        response = app.test_client().get(
            "/api/v1/admin/products", headers={"Authorization": token, "X-Custom-Secret": "synthetic-header-secret"},
        )
    assert response.status_code == 200
    assert service.call_args.kwargs["token"] == token
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    assert "synthetic-admin-secret" not in logs
    assert "synthetic-header-secret" not in logs


def test_admin_product_upstream_error_does_not_log_credentials(capsys, caplog):
    token = "Bearer synthetic-admin-secret"
    private = "synthetic-upstream-secret"
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.controllers.admin_products_controller.get_product_by_bgg_id_service", side_effect=UpstreamError(private)), \
            patch("app._append_incoming_log"), patch("app._opkey_before_request", return_value=None), \
            patch("os.path.exists", return_value=False), patch("builtins.open", create=True) as file_open:
        response = app.test_client().get("/api/v1/admin/products/123", headers={"Authorization": token})
    assert response.status_code == 502
    assert private not in response.get_data(as_text=True)
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    assert "synthetic-admin-secret" not in logs and private not in logs


def test_admin_product_missing_returns_404_without_scanning():
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.controllers.admin_products_controller.get_product_by_bgg_id_service", side_effect=UpstreamError("missing", "PRODUCT_NOT_FOUND")), \
            patch("src.controllers.admin_products_controller.admin_list_products_service") as listing, \
            patch("os.path.exists", return_value=False):
        response = app.test_client().get("/api/v1/admin/products/123", headers={"Authorization": "Bearer token"})
    assert response.status_code == 404
    listing.assert_not_called()


@pytest.mark.parametrize("product_id", ["invalid", "0", "-1", "2147483648"])
def test_admin_product_rejects_invalid_id_before_core(product_id):
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.controllers.admin_products_controller.get_product_by_bgg_id_service") as service:
        response = app.test_client().get(f"/api/v1/admin/products/{product_id}", headers={"Authorization": "Bearer token"})
    assert response.status_code == 400
    service.assert_not_called()


def test_admin_product_failure_never_returns_cached_placeholder():
    failure = UpstreamError("private upstream detail")
    cached = mock_open(read_data='{"bgg_id":123,"name":"Cached"}\n')
    with patch("src.proxy.check_admin", return_value=True), \
            patch("src.services.get_product_by_bgg_id", side_effect=failure), \
            patch("src.controllers.admin_products_controller.get_product_by_bgg_id_service", side_effect=failure), \
            patch("os.path.exists", return_value=True), patch("builtins.open", cached), \
            patch("app._append_incoming_log"):
        response = app.test_client().get("/api/v1/admin/products/123", headers={"Authorization": "Bearer token"})
    assert response.status_code == 502
    assert b"private upstream detail" not in response.data


def test_direct_product_graphql_error_does_not_fall_back_to_listing():
    with patch("src.proxy._graphql_request", return_value={"errors": [{"message": "private detail"}]}), \
            patch("src.proxy.list_products") as listing:
        with pytest.raises(UpstreamError) as failure:
            proxy.get_product_by_bgg_id(123, "Bearer token")
    assert failure.value.code == "UPSTREAM_ERROR"
    listing.assert_not_called()


@pytest.mark.parametrize("payload,expected_code", [
    ({"data": {"productByBggId": None}}, "PRODUCT_NOT_FOUND"),
    ({"data": {}}, "UPSTREAM_ERROR"),
    ({"data": {"productByBggId": {}}}, "UPSTREAM_ERROR"),
])
def test_direct_product_distinguishes_missing_and_invalid_payload(payload, expected_code):
    with patch("src.proxy._graphql_request", return_value=payload):
        with pytest.raises(UpstreamError) as failure:
            proxy.get_product_by_bgg_id(123, "Bearer token")
    assert failure.value.code == expected_code


@pytest.mark.parametrize("result", ["admin", "invalid", "graphql_error", "transport_error"])
def test_admin_identity_check_does_not_log_tokens_or_payloads(result, capsys, caplog):
    token = "synthetic-token"
    secret = "synthetic-private-identity"
    payload = {
        "admin": {"data": {"me": {"id": "1", "isStaff": True, "isSuperuser": False, "email": secret}}},
        "invalid": {"data": {"me": None}, "detail": secret},
        "graphql_error": {"errors": [{"message": secret}]},
    }.get(result)
    caplog.set_level("INFO")
    with patch("src.proxy._graphql_request", side_effect=UpstreamError(secret) if result == "transport_error" else None, return_value=payload), \
            patch("builtins.open", create=True) as file_open:
        if result in ("graphql_error", "transport_error"):
            with pytest.raises(UpstreamError):
                proxy.check_admin(token)
        else:
            assert proxy.check_admin(token) is (True if result == "admin" else None)
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    assert token not in logs and secret not in logs


def test_admin_product_creation_service_does_not_log_credentials(capsys, caplog):
    token = "Bearer synthetic-creation-secret"
    op_key = "synthetic-op-key"
    upstream = {"data": {"createProduct": {"product": {"bggId": 123, "name": "Game"}, "userErrors": []}}}
    with patch("src.proxy._graphql_request", return_value=upstream) as send, patch("builtins.open", create=True) as file_open:
        services.admin_create_product({"name": "Game", "_auth_token": token, "_op_key": op_key})
    assert send.call_args.args[2] == token
    assert send.call_args.kwargs["op_key"] == op_key
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(file_open.mock_calls)
    assert "synthetic-creation-secret" not in logs and op_key not in logs


def test_product_creation_cache_failure_does_not_write_private_debug_details(capsys, caplog):
    from unittest.mock import mock_open

    private = "synthetic-private-cache-error"
    product_name = "synthetic-private-product-name"
    response = {"data": {"createProduct": {"product": {"bggId": 123, "name": product_name}, "userErrors": []}}}
    debug_file = mock_open()

    def open_file(path, *args, **kwargs):
        if path == "/tmp/bff-created-products.log":
            raise OSError(private)
        return debug_file(path, *args, **kwargs)

    with patch("src.proxy._graphql_request", return_value=response), patch("builtins.open", side_effect=open_file):
        result = services.admin_create_product({"name": product_name, "_auth_token": "synthetic-token"})
    assert result == {"bgg_id": 123, "name": product_name}
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text + str(debug_file.mock_calls)
    assert private not in logs and product_name not in logs
    debug_file.assert_not_called()


@pytest.mark.parametrize("scenario,status", [("missing", 401), ("denied", 403), ("outage", 502)])
def test_admin_auth_failures_remain_closed_and_sanitized(scenario, status, capsys, caplog):
    token = "Bearer synthetic-admin-secret"
    private = "synthetic-upstream-secret"
    with patch("src.proxy.check_admin", side_effect=UpstreamError(private) if scenario == "outage" else None, return_value=False) as check, \
            patch("src.services.list_products") as service, patch("app._append_incoming_log"), \
            patch("app._opkey_before_request", return_value=None), patch("builtins.open", create=True) as file_open:
        headers = {} if scenario == "missing" else {"Authorization": token}
        response = app.test_client().get("/api/v1/admin/products", headers=headers)
    assert response.status_code == status
    service.assert_not_called()
    assert check.called is (scenario != "missing")
    assert private not in response.get_data(as_text=True)
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err + caplog.text + str(file_open.mock_calls)


def test_admin_accepts_validated_operation_key_without_bearer():
    def authorize_operation():
        g.op_session_valid = True

    sample = {"items": [], "page": 1, "page_size": 50}
    with patch("app._opkey_before_request", side_effect=authorize_operation), patch("app._append_incoming_log"), \
            patch("src.proxy.check_admin") as check, patch("src.services.list_products", return_value=sample) as service:
        response = app.test_client().get("/api/v1/admin/products", headers={"X-Op-Key": "synthetic-op-key"})
    assert response.status_code == 200
    check.assert_not_called()
    assert service.call_args.kwargs["token"] is None
