"""REST-to-Core adapter tests for private chatbot conversations."""

import hashlib

import jwt
import pytest
import requests

import app as app_module
from app import app
from src import proxy
from src.chatbot import rate_limit


CHAT_CONVERSATIONS = "/api/v1/chat/conversations"
CONVERSATION_ID = "00000000-0000-4000-8000-000000000013"
ASSERTION_SECRET = "T023-synthetic-chat-assertion-secret-2026"
PRIVATE_CONTENT = "SYNTHETIC-CONVERSATION-CONTENT"
UPSTREAM_SENTINEL = "CORE-PRIVATE-FAILURE-SENTINEL"


def _conversation(content=PRIVATE_CONTENT):
    return {
        "id": CONVERSATION_ID,
        "messages": [
            {
                "id": "00000000-0000-4000-8000-000000000014",
                "role": "USER",
                "content": content,
                "createdAt": "2026-11-07T08:00:00+00:00",
                "sources": [],
            }
        ],
        "createdAt": "2026-11-07T08:00:00+00:00",
        "updatedAt": "2026-11-07T08:00:00+00:00",
        "expiresAt": "2026-12-07T08:00:00+00:00",
    }


class _CoreResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"upstream status {self.status_code}")

    def json(self):
        return self.payload


class _FakeCoreTransport:
    """Local-only GraphQL transport; no Core service or network is contacted."""

    def __init__(self):
        self.calls = []
        self.read_code = None
        self.read_conversation = _conversation()
        self.delete_code = None
        self.failure = None

    def post(self, url, *, json, headers=None, **kwargs):
        call = {
            "url": url,
            "query": json["query"],
            "variables": json["variables"],
            "headers": dict(headers or {}),
        }
        self.calls.append(call)
        if self.failure:
            raise requests.ConnectionError(self.failure)

        query = call["query"]
        if "me { id }" in query:
            return _CoreResponse({"data": {"me": {"id": "synthetic-buyer-id"}}})
        if "chatConversation(" in query:
            if self.read_code:
                return _CoreResponse(
                    {
                        "data": {
                            "chatConversation": {
                                "conversation": None,
                                "userErrors": [{"code": self.read_code}],
                            }
                        }
                    }
                )
            return _CoreResponse(
                {
                    "data": {
                        "chatConversation": {
                            "conversation": self.read_conversation,
                            "userErrors": [],
                        }
                    }
                }
            )
        if "recordChatExchange" in query:
            conversation = _conversation()
            conversation["messages"].append(
                {
                    "id": "00000000-0000-4000-8000-000000000015",
                    "role": "ASSISTANT",
                    "content": json["variables"]["assistantMessage"],
                    "createdAt": "2026-11-07T08:01:00+00:00",
                    "sources": [],
                }
            )
            return _CoreResponse(
                {
                    "data": {
                        "recordChatExchange": {
                            "conversation": conversation,
                            "userErrors": [],
                        }
                    }
                }
            )
        if "deleteChatConversation" in query:
            user_errors = [{"code": self.delete_code}] if self.delete_code else []
            return _CoreResponse(
                {
                    "data": {
                        "deleteChatConversation": {
                            "success": not bool(self.delete_code),
                            "userErrors": user_errors,
                        }
                    }
                }
            )
        raise AssertionError(f"Unexpected Core operation: {query}")


class _FakeRedisLimiter:
    """Supplies deterministic rate-limit counts without a Redis connection."""

    def __init__(self):
        self.keys = []

    def eval(self, _script, _key_count, key, *_args):
        self.keys.append(key)
        return 1


class _FakeAnswerService:
    def answer(self, _message):
        return {"answer": "Synthetic store-hours response", "sources": []}


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setitem(app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "_append_incoming_log", lambda entry: None)
    monkeypatch.setattr(
        app_module,
        "_get_chatbot_answer_service",
        lambda: _FakeAnswerService(),
    )
    monkeypatch.setenv("CHAT_ASSERTION_SECRET", ASSERTION_SECRET)
    monkeypatch.setenv("SALEOR_GRAPHQL_URL", "http://core.test/graphql/")

    core = _FakeCoreTransport()
    redis_limiter = _FakeRedisLimiter()
    monkeypatch.setattr(proxy.requests, "post", core.post)
    monkeypatch.setattr(rate_limit, "_client", lambda: redis_limiter)

    with app.test_client() as client:
        client.core_transport = core
        client.fake_redis_limiter = redis_limiter
        yield client


def _anonymous_client(client):
    client.set_cookie("chat_session", "a" * 48)
    return client.get_cookie("chat_session").value


def _assert_fresh_anonymous_assertion(call, cookie_value):
    assertion = call["headers"]["X-Chat-Assertion"]
    claims = jwt.decode(
        assertion,
        ASSERTION_SECRET,
        algorithms=["HS256"],
        audience="bgg-shop-core",
        issuer="bgg-shop-bff",
    )
    assert claims["sub"] == hashlib.sha256(cookie_value.encode()).hexdigest()
    assert claims["scope"] == "chat:conversations"
    return assertion


def test_anonymous_read_is_core_owned_uncached_and_signs_each_call(adapter):
    cookie_value = _anonymous_client(adapter)

    first = adapter.get(f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}")
    assert first.status_code == 200
    assert first.headers["Cache-Control"] == "no-store"
    assert first.get_json()["conversation"]["messages"][0]["content"] == PRIVATE_CONTENT

    # A subsequent read must come from Core again, not a BFF conversation cache.
    adapter.core_transport.read_conversation = _conversation("CORE_UPDATED_CONTENT")
    second = adapter.get(f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}")
    assert second.status_code == 200
    assert (
        second.get_json()["conversation"]["messages"][0]["content"]
        == "CORE_UPDATED_CONTENT"
    )

    calls = adapter.core_transport.calls
    assert len(calls) == 2
    assert all("chatConversation(" in call["query"] for call in calls)
    assert all(call["variables"] == {"id": CONVERSATION_ID} for call in calls)
    assert all(call["headers"].keys() == {"X-Chat-Assertion"} for call in calls)
    assertions = [
        _assert_fresh_anonymous_assertion(call, cookie_value) for call in calls
    ]
    assert assertions[0] != assertions[1]
    assert all("deleteChatConversation" not in call["query"] for call in calls)
    assert len(adapter.fake_redis_limiter.keys) == 2


def test_continuing_conversation_delegates_exchange_to_core(adapter):
    cookie_value = _anonymous_client(adapter)
    message = "What are your store hours?"

    response = adapter.post(
        f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}/messages",
        json={"message": message},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["conversation_id"] == CONVERSATION_ID
    assert message not in response.get_json()["answer"]
    calls = adapter.core_transport.calls
    assert len(calls) == 1
    assert "recordChatExchange" in calls[0]["query"]
    assert calls[0]["variables"]["conversationId"] == CONVERSATION_ID
    assert calls[0]["variables"]["userMessage"] == message
    assert calls[0]["headers"].keys() == {"X-Chat-Assertion"}
    _assert_fresh_anonymous_assertion(calls[0], cookie_value)
    assert len(adapter.fake_redis_limiter.keys) == 1


@pytest.mark.parametrize("scope_case", ["missing", "expired", "cross_scope"])
def test_read_returns_indistinguishable_not_found_for_unavailable_scopes(
    adapter, scope_case
):
    _anonymous_client(adapter)
    adapter.core_transport.read_code = "NOT_FOUND"

    response = adapter.get(f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}")

    assert response.status_code == 404, scope_case
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "code": "NOT_FOUND",
        "error": "The chat conversation was not found.",
    }
    assert PRIVATE_CONTENT not in response.get_data(as_text=True)
    assert len(adapter.core_transport.calls) == 1
    assert "chatConversation(" in adapter.core_transport.calls[0]["query"]


def test_delete_delegates_to_core_without_bff_retention(adapter):
    cookie_value = _anonymous_client(adapter)

    response = adapter.delete(f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}")

    assert response.status_code == 204
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_data() == b""
    calls = adapter.core_transport.calls
    assert len(calls) == 1
    assert "deleteChatConversation" in calls[0]["query"]
    assert calls[0]["variables"] == {"conversationId": CONVERSATION_ID}
    assert calls[0]["headers"].keys() == {"X-Chat-Assertion"}
    _assert_fresh_anonymous_assertion(calls[0], cookie_value)
    assert len(adapter.fake_redis_limiter.keys) == 1


@pytest.mark.parametrize(
    ("method", "core_operation"),
    [
        ("get", "chatConversation("),
        ("delete", "deleteChatConversation"),
    ],
)
def test_core_not_found_is_safe_for_read_and_delete(
    adapter, method, core_operation
):
    _anonymous_client(adapter)
    adapter.core_transport.delete_code = "NOT_FOUND"
    adapter.core_transport.read_code = "NOT_FOUND"

    response = getattr(adapter, method)(f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "code": "NOT_FOUND",
        "error": "The chat conversation was not found.",
    }
    assert PRIVATE_CONTENT not in response.get_data(as_text=True)
    assert len(adapter.core_transport.calls) == 1
    assert core_operation in adapter.core_transport.calls[0]["query"]


@pytest.mark.parametrize("method", ["get", "delete"])
def test_upstream_transport_failure_is_sanitized(adapter, method):
    _anonymous_client(adapter)
    adapter.core_transport.failure = UPSTREAM_SENTINEL

    response = getattr(adapter, method)(f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}")

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "code": "SERVICE_UNAVAILABLE",
        "error": "Chat is temporarily unavailable. Please try again.",
    }
    assert UPSTREAM_SENTINEL not in response.get_data(as_text=True)
    assert len(adapter.core_transport.calls) == 1


def test_authenticated_read_delegates_identity_to_core_not_request_scope(adapter):
    bearer = "Bearer synthetic-buyer-token"

    response = adapter.get(
        f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}",
        headers={"Authorization": bearer},
    )

    assert response.status_code == 200
    calls = adapter.core_transport.calls
    assert len(calls) == 2
    identity_call, read_call = calls
    assert "me { id }" in identity_call["query"]
    assert "chatConversation(" in read_call["query"]
    assert identity_call["headers"] == {"Authorization": bearer}
    assert read_call["headers"] == {"Authorization": bearer}
    assert PRIVATE_CONTENT not in str(read_call["variables"])
    assert read_call["variables"] == {"id": CONVERSATION_ID}
    assert len(adapter.fake_redis_limiter.keys) == 1
