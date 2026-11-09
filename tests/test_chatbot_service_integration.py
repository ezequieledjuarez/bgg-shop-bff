"""T015 route wiring contract: lazy grounded service -> Core -> public reply.

The expected seam is the existing create_local_chatbot_service factory, resolved
lazily by the app/controller. Only that provider is replaced; payload guards,
classification, the service adapter, and the GraphQL adapter remain real.
"""

import importlib.util
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import proxy
from src.chatbot import rate_limit, service


CONVERSATIONS = "/api/v1/chat/conversations"
CONVERSATION_ID = "00000000-0000-4000-8000-000000000015"
MESSAGE_ROUTE = f"{CONVERSATIONS}/{CONVERSATION_ID}/messages"
QUESTION = "Which payment methods does the store accept?"
ANSWER = "The store accepts debit cards and bank transfers."
NOW = "2026-11-07T08:00:00+00:00"
EXPIRES = "2026-12-07T08:00:00+00:00"
PROVIDER_DETAIL = "T015-PRIVATE-OLLAMA-CHROMA-EXCEPTION"


def _sources():
    # Exercise both allowed ChatSource shapes, including an omitted optional URL.
    return [
        {"title": "Approved payment FAQ", "url": "https://store.test/faq/payments"},
        {"title": "Approved store policy"},
    ]


class _CoreResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class _FakeCoreTransport:
    """Echo mutation inputs, so fake Core cannot repair lost answer/sources."""

    def __init__(self, events):
        self.calls = []
        self.events = events

    def post(self, url, *, json, headers=None, **kwargs):
        assert url == "http://core.test/graphql/"
        query, variables = json["query"], deepcopy(json["variables"])
        self.calls.append({"query": query, "variables": variables})
        conversation = {
            "id": CONVERSATION_ID,
            "messages": [],
            "createdAt": NOW,
            "updatedAt": NOW,
            "expiresAt": EXPIRES,
        }
        if "recordChatExchange(" in query:
            field = "recordChatExchange"
            self.events.append("record")
            conversation["messages"] = [
                {
                    "id": "synthetic-user-message",
                    "role": "USER",
                    "content": variables["userMessage"],
                    "sources": [],
                    "createdAt": NOW,
                },
                {
                    "id": "synthetic-assistant-message",
                    "role": "ASSISTANT",
                    "content": variables["assistantMessage"],
                    "sources": deepcopy(variables["sources"]),
                    "createdAt": NOW,
                },
            ]
        elif "createChatConversation" in query:
            field = "createChatConversation"
            self.events.append("create")
        else:
            raise AssertionError(f"Unexpected Core operation: {query}")
        return _CoreResponse(
            {"data": {field: {"conversation": conversation, "userErrors": []}}}
        )


class _FakeRedisLimiter:
    def __init__(self, events):
        self.keys = []
        self.events = events

    def eval(self, _script, key_count, key, *_args):
        assert key_count == 1
        self.keys.append(key)
        self.events.append("limit")
        return 1


@pytest.fixture
def chat(monkeypatch):
    """Fresh Flask app, anonymous identity, and local fakes for every test."""
    state = SimpleNamespace(
        events=[], provider_calls=[], answer_calls=[], logs=[], failure=None
    )
    state.core = _FakeCoreTransport(state.events)
    state.redis = _FakeRedisLimiter(state.events)

    class FakeGroundedService:
        def answer(self, query):
            state.answer_calls.append(query)
            state.events.append("answer")
            if state.failure is not None:
                raise state.failure
            return {"answer": ANSWER, "sources": _sources()}

    def fake_provider(*args, **kwargs):
        state.provider_calls.append((args, kwargs))
        state.events.append("provider")
        return FakeGroundedService()

    monkeypatch.setenv(
        "CHAT_ASSERTION_SECRET", "T015-synthetic-assertion-secret-local-tests-only"
    )
    monkeypatch.setenv("FLASK_SKIP_DOTENV", "1")
    monkeypatch.setenv("SALEOR_GRAPHQL_URL", "http://core.test/graphql/")
    monkeypatch.setattr(proxy.requests, "post", state.core.post)
    monkeypatch.setattr(rate_limit, "_client", lambda: state.redis)
    # Patch before app import: no RAG/LLM constructors or internals are mocked.
    monkeypatch.setattr(service, "create_local_chatbot_service", fake_provider)
    spec = importlib.util.spec_from_file_location(
        "_t015_chat_app", Path(__file__).resolve().parents[1] / "app.py"
    )
    app_module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, app_module)
    spec.loader.exec_module(app_module)
    state.app_module = app_module
    state.provider_calls_at_import = len(state.provider_calls)
    state.answer_calls_at_import = len(state.answer_calls)
    app_module.app.config["TESTING"] = True
    monkeypatch.setattr(app_module, "_append_incoming_log", state.logs.append)

    with app_module.app.test_client() as client:
        client.set_cookie("chat_session", "t" * 48)
        state.client = client
        yield state


def _assert_reply_shape(response):
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert set(body) == {
        "conversation_id", "answer", "sources", "recommendations", "created_at"
    }
    assert body["conversation_id"] == CONVERSATION_ID
    assert isinstance(body["answer"], str)
    assert isinstance(body["sources"], list)
    assert body["recommendations"] == []
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    return body


def test_in_scope_answer_and_sources_reach_core_and_existing_reply_shape(chat):
    response = chat.client.post(MESSAGE_ROUTE, json={"message": QUESTION})
    body = _assert_reply_shape(response)

    assert chat.answer_calls == [QUESTION], (
        "The in-scope route must invoke the grounded answer service, not fallback."
    )
    assert len(chat.provider_calls) == 1
    assert chat.events == ["limit", "provider", "answer", "record"]
    assert len(chat.core.calls) == 1
    assert chat.core.calls[0]["variables"] == {
        "conversationId": CONVERSATION_ID,
        "userMessage": QUESTION,
        "assistantMessage": ANSWER,
        "sources": _sources(),
    }
    assert body["answer"] == ANSWER
    assert body["sources"] == _sources()
    assert body["created_at"] == NOW


@pytest.mark.parametrize(
    ("message", "expected_answer"),
    [
        ("Hola buenos días", "Hola, soy Meeple, tu asistente. ¿En qué puedo ayudarte?"),
        ("Hello!", "Hello, I'm Meeple, your assistant. How can I help?"),
    ],
)
def test_pure_greeting_uses_deterministic_reply_without_provider_or_persistence(
    chat, message, expected_answer
):
    response = chat.client.post(MESSAGE_ROUTE, json={"message": message})
    body = _assert_reply_shape(response)

    assert body["answer"] == expected_answer
    assert body["sources"] == []
    assert chat.provider_calls == []
    assert chat.answer_calls == []
    assert chat.core.calls == []
    assert chat.events == ["limit"]


def test_greeting_with_store_question_still_uses_grounded_service(chat):
    message = "Hola, ¿qué medios de pago acepta la tienda?"
    response = chat.client.post(MESSAGE_ROUTE, json={"message": message})
    body = _assert_reply_shape(response)

    assert body["answer"] == ANSWER
    assert body["sources"] == _sources()
    assert chat.answer_calls == [message]
    assert len(chat.provider_calls) == 1
    assert chat.events == ["limit", "provider", "answer", "record"]
    assert chat.core.calls[0]["variables"]["userMessage"] == message


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"message": 15},
        {"message": "   "},
        {"message": "shipping " + "x" * 1992},  # 2,001 characters
        {"message": QUESTION, "unapproved_context": "synthetic-private-context"},
    ],
    ids=["null", "non-string", "blank", "over-limit", "extra-field"],
)
def test_payload_guard_precedes_grounded_service_and_persistence(chat, payload):
    response = chat.client.post(MESSAGE_ROUTE, json=payload)

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_REQUEST"
    assert response.headers["Cache-Control"] == "no-store"
    assert chat.provider_calls == []
    assert chat.answer_calls == []
    assert chat.core.calls == []
    assert chat.events == ["limit"]


@pytest.mark.parametrize(
    ("message", "private_marker"),
    [
        ("My password is T015-PRIVATE-PASSWORD", "T015-PRIVATE-PASSWORD"),
        ("Shipping to buyer-t015@example.test?", "buyer-t015@example.test"),
        ("Tell a joke about T015-OFF-TOPIC", "T015-OFF-TOPIC"),
        ("Tell me about it", "Tell me about it"),
    ],
    ids=["protected", "mixed-shop-and-personal", "out-of-scope", "unclear"],
)
def test_refused_input_never_reaches_service_core_or_public_echo(
    chat, caplog, message, private_marker
):
    response = chat.client.post(MESSAGE_ROUTE, json={"message": message})
    body = _assert_reply_shape(response)

    assert body["sources"] == []
    assert chat.provider_calls_at_import == 0
    assert chat.answer_calls_at_import == 0
    assert chat.provider_calls == []
    assert chat.answer_calls == []
    assert chat.core.calls == []
    assert chat.events == ["limit"]
    assert private_marker not in response.get_data(as_text=True)
    assert private_marker not in repr(chat.logs)
    assert private_marker not in caplog.text


def test_grounded_failure_is_safe_and_does_not_persist_user_message(chat, caplog):
    chat.failure = service.ChatbotServiceUnavailable(PROVIDER_DETAIL)
    response = chat.client.post(MESSAGE_ROUTE, json={"message": QUESTION})

    assert response.status_code == 503, (
        "Grounded service failure must not be replaced by a persisted fallback."
    )
    assert response.get_json() == {
        "code": "SERVICE_UNAVAILABLE",
        "error": "Chat is temporarily unavailable. Please try again.",
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert chat.answer_calls == [QUESTION]
    assert chat.events == ["limit", "provider", "answer"]
    assert chat.core.calls == []
    public = response.get_data(as_text=True)
    assert QUESTION not in public
    assert PROVIDER_DETAIL not in public
    assert "ChatbotServiceUnavailable" not in public
    assert PROVIDER_DETAIL not in repr(chat.logs)
    assert PROVIDER_DETAIL not in caplog.text


def test_app_import_and_conversation_creation_do_not_initialize_local_rag(chat):
    assert chat.provider_calls_at_import == 0
    assert chat.answer_calls_at_import == 0

    response = chat.client.post(CONVERSATIONS)

    assert response.status_code == 201
    assert response.get_json()["conversation"] == {
        "id": CONVERSATION_ID,
        "messages": [],
        "created_at": NOW,
        "updated_at": NOW,
        "expires_at": EXPIRES,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert chat.provider_calls == []
    assert chat.answer_calls == []
    assert chat.events == ["limit", "create"]
