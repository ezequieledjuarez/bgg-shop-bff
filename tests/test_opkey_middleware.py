from unittest.mock import patch

import pytest
import requests
from flask import Flask, g

from src.auth import admin_required
from src import opkey_middleware, proxy, services


@pytest.fixture
def client():
    app = Flask(__name__)
    opkey_middleware.init_app(app)

    @app.route("/admin/allowed", methods=["GET", "POST"])
    @app.route("/admin/other", methods=["GET"])
    @admin_required
    def protected():
        return "ok"

    return app.test_client()


def test_opkey_validation_is_scoped_to_path_and_method(client):
    raw_key = "synthetic-operation-key"
    headers = {"X-Op-Key": raw_key}

    def validate(key, path, method):
        return {"valid": path == "/admin/allowed" and method == "GET"}

    with patch.object(opkey_middleware, "validate_op_key_with_core", side_effect=validate) as check:
        assert client.get("/admin/allowed", headers=headers).status_code == 200
        assert client.get("/admin/allowed", headers=headers).status_code == 200
        assert client.get("/admin/other", headers=headers).status_code == 401
        assert client.post("/admin/allowed", headers=headers).status_code == 401
    assert check.call_count == 4


def test_revoked_key_is_rejected_on_next_request(client):
    headers = {"X-Op-Key": "synthetic-operation-key"}
    with patch.object(
        opkey_middleware, "validate_op_key_with_core", side_effect=[{"valid": True}, {"valid": False}]
    ) as check:
        assert client.get("/admin/allowed", headers=headers).status_code == 200
        assert client.get("/admin/allowed", headers=headers).status_code == 401
    assert check.call_count == 2


@pytest.mark.parametrize("configured", ["", "changeme-internal-secret"])
def test_validation_fails_closed_without_internal_secret(configured, monkeypatch):
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", configured)
    with patch.object(opkey_middleware.requests, "post") as post:
        assert opkey_middleware.validate_op_key_with_core("synthetic-key", "/admin/allowed", "GET") is None
    post.assert_not_called()


def test_validation_sends_configured_secret(monkeypatch):
    secret = "synthetic-internal-secret-0123456789-abcdef"
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", secret)
    with patch.object(opkey_middleware.requests, "post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"valid": True}
        assert opkey_middleware.validate_op_key_with_core("synthetic-key", "/admin/allowed", "GET") == {"valid": True}
    assert post.call_args.kwargs["headers"] == {"X-Internal-Secret": secret}
    assert post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("payload", [{"valid": "false"}, {"valid": 1}, {}, [], None])
def test_malformed_core_response_never_grants_access(client, monkeypatch, payload):
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", "synthetic-internal-secret-0123456789-abcdef")
    with patch.object(opkey_middleware.requests, "post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = payload
        response = client.get("/admin/allowed", headers={"X-Op-Key": "synthetic-operation-key"})
    assert response.status_code == 502


@pytest.mark.parametrize("result", [None, {"valid": False}])
def test_opkey_validation_failure_distinguishes_upstream_from_invalid(client, result):
    with patch.object(opkey_middleware, "validate_op_key_with_core", return_value=result):
        response = client.get("/admin/allowed", headers={"X-Op-Key": "synthetic-key"})
    assert response.status_code == (502 if result is None else 401)


def test_valid_jwt_is_not_blocked_by_opkey_validation_failure(client):
    with patch.object(opkey_middleware, "validate_op_key_with_core", return_value=None), \
            patch.object(proxy, "check_admin", return_value=True):
        response = client.get("/admin/allowed", headers={"X-Op-Key": "synthetic-key", "Authorization": "Bearer valid"})
    assert response.status_code == 200


@pytest.mark.parametrize("admin,expected", [(None, 401), (False, 403), (True, 200)])
def test_jwt_identity_decides_even_when_opkey_validation_fails(client, admin, expected):
    with patch.object(opkey_middleware, "validate_op_key_with_core", return_value=None), \
            patch.object(proxy, "check_admin", return_value=admin):
        response = client.get("/admin/allowed", headers={"X-Op-Key": "synthetic-key", "Authorization": "Bearer token"})
    assert response.status_code == expected


@pytest.mark.parametrize("failure", ["timeout", "http_error", "redirect", "invalid_json"])
def test_opkey_core_transport_failures_return_502(client, monkeypatch, failure):
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", "synthetic-internal-secret-0123456789-abcdef")
    with patch.object(opkey_middleware.requests, "post") as post:
        if failure == "timeout":
            post.side_effect = requests.Timeout("private detail")
        else:
            post.return_value.status_code = {"http_error": 503, "redirect": 302}.get(failure, 200)
            post.return_value.json.side_effect = ValueError("private detail")
        response = client.get("/admin/allowed", headers={"X-Op-Key": "synthetic-key"})
    assert response.status_code == 502
    assert b"private detail" not in response.data


def test_whoami_for_jwt_and_opkey_forwards_jwt_and_validated_delegation(monkeypatch):
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", "synthetic-internal-secret-0123456789-abcdef")
    app = Flask(__name__)
    opkey_middleware.init_app(app)

    @app.get("/api/v1/admin/promotions")
    @admin_required
    def protected():
        return "ok"

    def post(url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        if url.endswith("/internal/op-validate"):
            response._content = b'{"valid": true}'
        else:
            assert "WhoAmI" in kwargs["json"]["query"]
            assert kwargs["headers"]["Authorization"] == "Bearer jwt-user"
            assert kwargs["headers"]["X-Op-Key"] == "synthetic-key"
            response._content = b'{"data":{"me":{"id":"7","email":"jwt@example.test","isStaff":true,"isSuperuser":false}}}'
        return response

    with patch.object(opkey_middleware.requests, "post", side_effect=post) as request_post:
        response = app.test_client().get("/api/v1/admin/promotions", headers={"X-Op-Key": "synthetic-key", "Authorization": "Bearer jwt-user"})
    assert response.status_code == 200
    assert request_post.call_count == 2


@pytest.mark.parametrize("status,body", [
    (200, b'{"errors":[{"message":"invalid field"}]}'),
    (403, b'{"error":"Forbidden"}'),
])
def test_promotion_schema_error_and_denied_delegation_remain_upstream_errors(status, body):
    response = requests.Response()
    response.status_code = status
    response._content = body
    app = Flask(__name__)
    with app.test_request_context("/api/v1/admin/promotions", headers={"X-Op-Key": "synthetic-key"}), \
            patch.object(proxy.requests, "post", return_value=response), pytest.raises(proxy.UpstreamError):
        g.op_session_valid = True
        proxy.list_promotions()


@pytest.mark.parametrize("valid", [True, False])
def test_graphql_delegates_only_a_validated_operation(valid, monkeypatch):
    secret = "synthetic-internal-secret-0123456789-abcdef"
    monkeypatch.setenv("OPKEY_INTERNAL_SECRET", secret)
    app = Flask(__name__)
    with app.test_request_context("/api/v1/admin/products", method="POST", headers={"X-Op-Key": "synthetic-key"}):
        g.op_session_valid = valid
        with patch.object(proxy.requests, "post") as post:
            post.return_value.json.return_value = {"data": {}}
            proxy._graphql_request("mutation Test { test }", {})
    headers = post.call_args.kwargs["headers"]
    if valid:
        assert headers["X-Op-Key"] == "synthetic-key"
        assert headers["X-Internal-Secret"] == secret
        assert headers["X-Op-Method"] == "POST"
        assert headers["X-Op-Path"] == "/api/v1/admin/products"
    else:
        assert "X-Internal-Secret" not in headers
        assert "X-Op-Key" not in headers
    assert post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("service,proxy_name,args,token_position", [
    (services.admin_create_product, "create_product", ({"name": "Game", "_op_key": "synthetic-key"},), 1),
    (services.admin_update_product, "update_product", ("1", {"name": "Game", "_op_key": "synthetic-key"}), 2),
    (services.admin_create_promotion, "create_promotion", ({"name": "Sale", "_op_key": "synthetic-key"},), 1),
])
def test_opkey_never_uses_shared_admin_token(monkeypatch, service, proxy_name, args, token_position):
    monkeypatch.setenv("BFF_ADMIN_TOKEN", "synthetic-shared-admin-token")
    with patch.object(proxy, proxy_name, return_value={}) as create, patch("builtins.open") as file_open:
        service(*args)
    assert create.call_args.args[token_position] is None
    assert create.call_args.kwargs["op_key"] == "synthetic-key"
    file_open.assert_not_called()


def test_browser_preflight_allows_operation_key_on_admin_put():
    from app import app

    with patch("app._append_incoming_log"):
        response = app.test_client().options("/api/v1/admin/products/1", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "X-Op-Key, Content-Type",
        })
    assert "PUT" in response.headers.get("Access-Control-Allow-Methods", "")
    assert "x-op-key" in response.headers.get("Access-Control-Allow-Headers", "").lower()