import json
from unittest.mock import patch

import pytest
from flask import g

from app import app
from src import proxy
from src import services
from src.proxy import UpstreamError

AUTH = {"Authorization": "Bearer admin-token"}
SERVICE = "src.controllers.admin_audit_controller.admin_list_audit_service"


def _get(query="", headers=AUTH, **kwargs):
    with patch("src.proxy.check_admin", return_value=True):
        return app.test_client().get(f"/api/v1/admin/audit{query}", headers=headers, **kwargs)


def test_audit_requires_admin_authentication():
    assert app.test_client().get("/api/v1/admin/audit").status_code == 401


def test_audit_forwards_validated_filters_and_sets_no_store():
    page = {"items": [], "next_cursor": None}
    with patch(SERVICE, return_value=page) as service:
        resp = _get(
            "?entity_type=coupon&entity_id=7&actor_id=3&action=coupon_updated"
            "&created_from=2026-01-01T00:00:00Z&created_to=2026-02-01T02:00:00%2B02:00&limit=25&cursor=abc"
        )
    assert resp.status_code == 200
    assert resp.get_json() == page
    assert resp.headers["Cache-Control"] == "no-store"
    filters = service.call_args.args[0]
    assert filters["limit"] == 25 and filters["entity_type"] == "coupon" and filters["cursor"] == "abc"
    assert filters["created_from"] == "2026-01-01T00:00:00+00:00"
    assert filters["created_to"] == "2026-02-01T00:00:00+00:00"


def test_validated_opkey_is_forwarded_through_audit_controller_and_service():
    with patch("app._opkey_before_request", side_effect=lambda: setattr(g, "op_session_valid", True)), \
            patch(SERVICE, return_value={"items": [], "next_cursor": None}) as service:
        response = app.test_client().get(
            "/api/v1/admin/audit",
            headers={"X-Op-Key": "synthetic-op-key"},
        )
    assert response.status_code == 200
    service.assert_called_once_with({}, None, "synthetic-op-key")

    with patch("src.services.proxy.list_admin_audit", return_value={}) as upstream:
        services.admin_list_audit({}, None, "synthetic-op-key")
    upstream.assert_called_once_with({}, None, op_key="synthetic-op-key")


@pytest.mark.parametrize("query,field", [
    ("?limit=0", "limit"),
    ("?limit=101", "limit"),
    ("?limit=abc", "limit"),
    ("?limit=-1", "limit"),
    ("?created_from=2026-01-01T00:00:00", "created_from"),
    ("?created_to=nope", "created_to"),
    ("?created_from=2026-02-01T00:00:00Z&created_to=2026-01-01T00:00:00Z", "created_from"),
    ("?entity_type=" + "x" * 151, "entity_type"),
    ("?entity_id=", "entity_id"),
    ("?cursor=" + "x" * 513, "cursor"),
    ("?unknown=1", "query"),
    ("?limit=1&limit=2", "limit"),
])
def test_audit_rejects_invalid_filters_without_calling_upstream(query, field):
    with patch(SERVICE) as service:
        resp = _get(query)
    assert resp.status_code == 400
    assert resp.get_json()["errors"][0]["field"] == field
    assert resp.headers["Cache-Control"] == "no-store"
    service.assert_not_called()


@pytest.mark.parametrize("code,status", [("UNAUTHENTICATED", 401), ("FORBIDDEN", 403)])
def test_audit_maps_core_authorization_errors(code, status):
    with patch(SERVICE, side_effect=UpstreamError("internal secret detail", code, user_error=True)):
        resp = _get()
    assert resp.status_code == status
    assert "secret" not in resp.get_data(as_text=True)


def test_audit_maps_core_invalid_to_public_field():
    with patch(SERVICE, side_effect=UpstreamError("Traceback http://core:8000", "INVALID", ["cursor"], user_error=True)):
        resp = _get("?cursor=bad")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["errors"][0]["field"] == "cursor"
    assert "Traceback" not in resp.get_data(as_text=True)


def test_audit_upstream_failure_is_static_502():
    with patch(SERVICE, side_effect=UpstreamError("http://core:8000/graphql password=hunter2 Traceback")):
        resp = _get()
    assert resp.status_code == 502
    assert resp.get_json() == {"error": "upstream GraphQL request failed"}


def _graphql(payload):
    return patch("src.proxy._graphql_request", return_value=payload)


def test_proxy_maps_and_redacts_changes():
    record = {
        "id": 9, "actorId": "3", "action": "coupon_updated", "entityType": "coupon", "entityId": "7",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "before": json.dumps({"code": "A", "api_key": "k", "nested": [{"Card_Number": "4111"}]}),
        "after": None,
    }
    with _graphql({"data": {"adminAuditLogs": {"records": [record], "nextCursor": "n"}}}) as request:
        result = proxy.list_admin_audit({"limit": 5, "entity_type": "coupon"}, "Bearer t")
    assert request.call_args.args[1] == {"limit": 5, "entityType": "coupon"}
    item = result["items"][0]
    assert item["changes"] == {
        "before": {"code": "A", "api_key": "[REDACTED]", "nested": [{"Card_Number": "[REDACTED]"}]},
        "after": None,
    }
    assert item["actor_id"] == "3" and result["next_cursor"] == "n"


def test_proxy_parses_graphql_error_extensions_and_hides_messages():
    def failure(code, field=None):
        extensions = {"code": code, **({"field": field} if field else {})}
        return {"errors": [{"message": "SELECT * FROM audit_log secret", "extensions": extensions}]}

    for code in ("UNAUTHENTICATED", "FORBIDDEN"):
        with _graphql(failure(code)), pytest.raises(UpstreamError) as caught:
            proxy.list_admin_audit({})
        assert caught.value.code == code and "SELECT" not in str(caught.value)
    with _graphql(failure("INVALID", "created_from")), pytest.raises(UpstreamError) as caught:
        proxy.list_admin_audit({})
    assert caught.value.field == ["created_from"]
    with _graphql(failure("SERVER_ERROR")), pytest.raises(UpstreamError) as caught:
        proxy.list_admin_audit({})
    assert not caught.value.user_error and "SELECT" not in str(caught.value)
