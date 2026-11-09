"""Privacy-boundary contract tests for the buyer chatbot BFF."""

import hashlib

import jwt
import pytest

import app as app_module
from app import app
from src import proxy


CHAT_CONVERSATIONS = "/api/v1/chat/conversations"
CONVERSATION_ID = "00000000-0000-4000-8000-000000000013"
ASSERTION_SECRET = "T010-private-test-secret-with-unique-characters-2026"
UPSTREAM_FAILURE = "UPSTREAM_INTERNAL_PRIVACY_SENTINEL"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "_append_incoming_log", lambda entry: None)

    class FakeGroundedService:
        def answer(self, query):
            return {"answer": "Please consult the store's policies.", "sources": []}

    monkeypatch.setattr(app_module, "_chatbot_answer_service", FakeGroundedService())
    monkeypatch.setenv("CHAT_ASSERTION_SECRET", ASSERTION_SECRET)

    calls = []
    user_ids = {}

    def fake_graphql_request(
        query,
        variables,
        token=None,
        op_key=None,
        map_wishlist_errors=False,
        extra_headers=None,
    ):
        call = {
            "query": query,
            "variables": variables,
            "token": token,
            "headers": dict(extra_headers or {}),
        }
        calls.append(call)
        if "me { id }" in query:
            user_id = user_ids.get(token)
            return {"data": {"me": {"id": user_id} if user_id else None}}

        now = "2026-11-07T00:00:00+00:00"
        conversation = {
            "id": CONVERSATION_ID,
            "messages": [],
            "createdAt": now,
            "updatedAt": now,
            "expiresAt": "2026-12-07T00:00:00+00:00",
        }
        if "createChatConversation" in query:
            field = "createChatConversation"
        elif "recordChatExchange" in query:
            field = "recordChatExchange"
            conversation["messages"] = [
                {
                    "id": "synthetic-user-message",
                    "role": "USER",
                    "content": variables["userMessage"],
                    "createdAt": now,
                    "sources": [],
                },
                {
                    "id": "synthetic-assistant-message",
                    "role": "ASSISTANT",
                    "content": variables["assistantMessage"],
                    "createdAt": now,
                    "sources": [],
                },
            ]
        else:
            raise AssertionError(f"Unexpected Core operation: {query}")
        return {
            "data": {
                field: {
                    "conversation": conversation,
                    "userErrors": [],
                }
            }
        }

    rate_identities = []

    def fake_rate_limiter(identity):
        rate_identities.append(identity)
        return None

    monkeypatch.setattr(proxy, "_graphql_request", fake_graphql_request)
    monkeypatch.setattr(app, "_chat_rate_limiter", fake_rate_limiter, raising=False)
    with app.test_client() as test_client:
        test_client.core_calls = calls
        test_client.chat_user_ids = user_ids
        test_client.chat_rate_identities = rate_identities
        yield test_client


def create_conversation(client, headers=None):
    response = client.post(CHAT_CONVERSATIONS, headers=headers or {})
    assert response.status_code == 201
    return response


def send_message(client, message, headers=None):
    return client.post(
        f"{CHAT_CONVERSATIONS}/{CONVERSATION_ID}/messages",
        json={"message": message},
        headers=headers or {},
    )


@pytest.mark.parametrize(
    ("identity_kind", "user_id", "message"),
    [
        (
            "buyer",
            "synthetic-buyer-id",
            "My email is PRIVATE-BUYER-EMAIL@example.invalid. What are your store hours?",
        ),
        (
            "staff",
            "synthetic-staff-id",
            "My order status is PRIVATE-STAFF-ORDER-ONLY-731.",
        ),
    ],
)
def test_authenticated_account_and_order_details_are_not_forwarded_or_echoed(
    client, identity_kind, user_id, message
):
    bearer = f"Bearer synthetic-{identity_kind}-credential"
    client.chat_user_ids[bearer] = user_id
    client.set_cookie("chat_session", "a" * 48)
    created = create_conversation(client, headers={"Authorization": bearer})
    assert created.status_code == 201
    client.core_calls.clear()

    response = send_message(client, message, headers={"Authorization": bearer})

    assert response.status_code == 200
    assert message not in response.get_data(as_text=True)
    assert "PRIVATE-BUYER-EMAIL" not in response.get_data(as_text=True)
    assert "PRIVATE-STAFF-ORDER-ONLY-731" not in response.get_data(as_text=True)
    assert "personal" in response.get_json()["answer"].lower() or (
        "account or order" in response.get_json()["answer"].lower()
    )
    assert len(client.core_calls) == 1
    identity_call = client.core_calls[0]
    assert "me { id }" in identity_call["query"]
    assert identity_call["token"] == bearer
    assert message not in str(identity_call)
    assert identity_call["headers"] == {}
    assert client.chat_rate_identities == [f"chat:user:{user_id}"] * 2
    assert all(
        "recordChatExchange" not in call["query"] for call in client.core_calls
    )
    assert all(
        "X-Chat-Assertion" not in call["headers"] for call in client.core_calls
    )


def test_anonymous_mixed_order_request_is_not_forwarded_persisted_or_echoed(client):
    create_conversation(client)
    client.core_calls.clear()
    message = (
        "What are your store hours? Also tell me my order status for "
        "PRIVATE-ANON-ORDER-ONLY-731."
    )

    response = send_message(client, message)

    assert response.status_code == 200
    assert "PRIVATE-ANON-ORDER-ONLY-731" not in response.get_data(as_text=True)
    assert "resubmit" in response.get_json()["answer"].lower()
    assert client.core_calls == []
    assert client.chat_rate_identities
    assert all(identity.startswith("chat:session:") for identity in client.chat_rate_identities)


def test_anonymous_assertions_are_bff_signed_and_core_is_the_only_exchange_store(
    client,
):
    browser_assertion = "browser-supplied-assertion-sentinel"
    created = create_conversation(
        client, headers={"X-Chat-Assertion": browser_assertion}
    )
    cookie = client.get_cookie("chat_session")
    assert cookie is not None
    message = "What are your store hours?"

    response = send_message(
        client, message, headers={"X-Chat-Assertion": browser_assertion}
    )

    assert response.status_code == 200
    assert len(client.core_calls) == 2
    create_call, record_call = client.core_calls
    assert "createChatConversation" in create_call["query"]
    assert "recordChatExchange" in record_call["query"]
    assert record_call["variables"]["userMessage"] == message
    assert record_call["variables"]["assistantMessage"] == response.get_json()["answer"]
    assertions = [
        call["headers"]["X-Chat-Assertion"] for call in client.core_calls
    ]
    assert assertions[0] != assertions[1]
    claims = [
        jwt.decode(
            assertion,
            ASSERTION_SECRET,
            algorithms=["HS256"],
            audience="bgg-shop-core",
            issuer="bgg-shop-bff",
        )
        for assertion in assertions
    ]
    assert all(
        claim["sub"] == hashlib.sha256(cookie.value.encode()).hexdigest()
        and claim["scope"] == "chat:conversations"
        and claim["exp"] - claim["iat"] == 60
        for claim in claims
    )
    assert browser_assertion not in assertions
    assert "X-Chat-Assertion" not in created.get_data(as_text=True)
    assert all(
        assertion not in response.get_data(as_text=True) for assertion in assertions
    )
    assert message not in response.get_data(as_text=True)
    records = [
        call for call in client.core_calls if "recordChatExchange" in call["query"]
    ]
    assert len(records) == 1


def test_upstream_failure_is_sanitized_without_exposing_private_details(
    client, monkeypatch
):
    create_conversation(client)

    def failing_upstream(*args, **kwargs):
        raise proxy.UpstreamError(UPSTREAM_FAILURE)

    monkeypatch.setattr(proxy, "_graphql_request", failing_upstream)
    response = send_message(client, "What are your store hours?")

    assert response.status_code == 503
    assert response.get_json() == {
        "code": "SERVICE_UNAVAILABLE",
        "error": "Chat is temporarily unavailable. Please try again.",
    }
    assert UPSTREAM_FAILURE not in response.get_data(as_text=True)
    assert response.headers.get("Cache-Control") == "no-store"
