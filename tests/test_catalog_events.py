import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from flask import Request as FlaskRequest

from app import app


ROOT = Path(__file__).resolve().parents[1]
EVENT_PATH = "/internal/v1/catalog-events"
SECRET = "test-catalog-events-secret-with-enough-entropy"


@pytest.fixture(autouse=True)
def disable_legacy_request_file_logging(monkeypatch):
    monkeypatch.setattr("app._append_incoming_log", lambda _entry: None)


def event_payload(event_type="product.changed"):
    aggregate_type = {
        "product.changed": "product",
        "stock.changed": "stock",
        "promotion.changed": "promotion",
    }[event_type]
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "aggregate_type": aggregate_type,
        "aggregate_id": "42",
    }


def signature(body, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_openapi_defines_the_internal_versioned_catalog_event_contract():
    openapi = yaml.safe_load(
        (ROOT / "specs" / "openapi.yaml").read_text(encoding="utf-8")
    )
    operation = openapi["paths"][EVENT_PATH]["post"]
    schema = openapi["components"]["schemas"]["CatalogEvent"]

    assert operation["requestBody"]["required"] is True
    assert operation["parameters"][0]["name"] == "X-Catalog-Event-Signature"
    assert set(schema["required"]) == {
        "event_id",
        "event_type",
        "occurred_at",
        "aggregate_type",
        "aggregate_id",
    }
    assert set(schema["properties"]) == set(schema["required"])
    assert schema["properties"]["event_type"]["enum"] == [
        "product.changed",
        "stock.changed",
        "promotion.changed",
    ]


def test_catalog_event_rejects_missing_or_invalid_signature_without_disclosing_details(monkeypatch):
    monkeypatch.setenv("CATALOG_EVENTS_HMAC_SECRET", SECRET)
    payload = event_payload()
    body = json.dumps(payload, separators=(",", ":")).encode()
    client = app.test_client()

    missing = client.post(EVENT_PATH, data=body, content_type="application/json")
    invalid = client.post(
        EVENT_PATH,
        data=body,
        content_type="application/json",
        headers={"X-Catalog-Event-Signature": "sha256=" + ("0" * 64)},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert SECRET.encode() not in missing.data + invalid.data
    assert b"signature" not in missing.data.lower() + invalid.data.lower()


def test_oversized_unauthenticated_event_is_rejected_before_body_read(monkeypatch):
    class TrackingRequest(FlaskRequest):
        body_read = False

        def get_data(self, *args, **kwargs):
            type(self).body_read = True
            return super().get_data(*args, **kwargs)

    monkeypatch.setattr(app, "request_class", TrackingRequest)
    monkeypatch.delenv("CATALOG_EVENTS_HMAC_SECRET", raising=False)
    monkeypatch.delenv("OPKEY_INTERNAL_SECRET", raising=False)
    TrackingRequest.body_read = False
    response = app.test_client().post(
        EVENT_PATH,
        data=b"x" * 2048,
        content_type="application/json",
    )

    assert response.status_code == 413
    assert response.get_json() == {"error": "invalid event"}
    assert TrackingRequest.body_read is False


def test_catalog_event_fails_closed_when_shared_secret_is_missing(monkeypatch):
    monkeypatch.delenv("CATALOG_EVENTS_HMAC_SECRET", raising=False)
    monkeypatch.delenv("OPKEY_INTERNAL_SECRET", raising=False)
    response = app.test_client().post(
        EVENT_PATH,
        json=event_payload(),
        headers={"X-Catalog-Event-Signature": "sha256=" + ("0" * 64)},
    )

    assert response.status_code == 503
    assert SECRET.encode() not in response.data


def test_catalog_event_requires_exact_minimal_envelope(monkeypatch):
    monkeypatch.setenv("CATALOG_EVENTS_HMAC_SECRET", SECRET)
    payload = event_payload()
    payload["product"] = {"private": "must not be accepted"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = app.test_client().post(
        EVENT_PATH,
        data=body,
        content_type="application/json",
        headers={"X-Catalog-Event-Signature": signature(body)},
    )

    assert response.status_code == 400
    assert b"private" not in response.data


@pytest.mark.parametrize(
    "changes",
    [
        {"event_type": "unknown.changed"},
        {"event_id": "not-a-uuid"},
        {"occurred_at": "2026-11-02T15:00:00+01:00"},
        {"aggregate_type": "promotion"},
        {"aggregate_id": ""},
    ],
)
def test_catalog_event_rejects_envelopes_outside_contract(monkeypatch, changes):
    monkeypatch.setenv("CATALOG_EVENTS_HMAC_SECRET", SECRET)
    payload = event_payload()
    payload.update(changes)
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = app.test_client().post(
        EVENT_PATH,
        data=body,
        content_type="application/json",
        headers={"X-Catalog-Event-Signature": signature(body)},
    )

    assert response.status_code == 400
    assert b"invalid event" in response.data


def test_catalog_event_uses_hmac_of_exact_body_and_invalidates_generation(monkeypatch):
    monkeypatch.setenv("CATALOG_EVENTS_HMAC_SECRET", SECRET)
    payload = event_payload("stock.changed")
    body = json.dumps(payload, separators=(",", ":")).encode()
    with patch("src.catalog_cache.invalidate_catalog_cache") as invalidate:
        response = app.test_client().post(
            EVENT_PATH,
            data=body,
            content_type="application/json",
            headers={"X-Catalog-Event-Signature": signature(body)},
        )

    assert response.status_code == 204
    invalidate.assert_called_once_with(payload["event_id"])


def test_catalog_event_returns_retryable_error_when_invalidation_fails(monkeypatch):
    monkeypatch.setenv("CATALOG_EVENTS_HMAC_SECRET", SECRET)
    payload = event_payload("promotion.changed")
    body = json.dumps(payload, separators=(",", ":")).encode()
    with patch(
        "src.catalog_cache.invalidate_catalog_cache",
        side_effect=RuntimeError("redis credentials leaked"),
    ):
        response = app.test_client().post(
            EVENT_PATH,
            data=body,
            content_type="application/json",
            headers={"X-Catalog-Event-Signature": signature(body)},
        )

    assert response.status_code == 503
    assert b"redis credentials leaked" not in response.data
