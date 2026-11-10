"""Black-box contract tests for the buyer chatbot's request guardrails."""

import hashlib
import secrets

import jwt
import pytest

import app as app_module
from app import app
from src import proxy as proxy_module
from src.chatbot.guardrails import classify_message, reply_for_classification


CHAT_CONVERSATIONS = "/api/v1/chat/conversations"


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        ("Hola buenos días", "greeting"),
        ("¡HOLA, BUENAS TARDES!", "greeting"),
        ("Buenas noches.", "greeting"),
        ("Hello!", "greeting"),
        ("Good morning.", "greeting"),
        ("Hi, good evening!", "greeting"),
        ("Hola, ¿qué medios de pago acepta la tienda?", "in_scope"),
        ("Hola, dime el estado de mi pedido.", "protected"),
        ("Hola, cuéntame un chiste.", "out_of_scope"),
        ("Hola, ¿qué medios de pago y cuál es mi contraseña?", "mixed"),
    ],
)
def test_greetings_are_full_matches_after_safety_classification(message, classification):
    assert classify_message(message) == classification


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Hola buenos días", "Hola, soy Meeple, tu asistente. ¿En qué puedo ayudarte?"),
        ("Hello!", "Hello, I'm Meeple, your assistant. How can I help?"),
    ],
)
def test_greeting_reply_uses_the_matching_language(message, expected):
    assert reply_for_classification("greeting", message) == expected


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "_append_incoming_log", lambda entry: None)

    class FakeGroundedService:
        def answer(self, query):
            return {"answer": "Please consult the store's policies.", "sources": []}

    monkeypatch.setattr(app_module, "_chatbot_answer_service", FakeGroundedService())
    secret = secrets.token_urlsafe(48)
    monkeypatch.setenv("CHAT_ASSERTION_SECRET", secret)

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
            "id": "00000000-0000-4000-8000-000000000013",
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
                    "id": "user-message-id",
                    "role": "USER",
                    "content": variables["userMessage"],
                    "createdAt": now,
                    "sources": [],
                },
                {
                    "id": "assistant-message-id",
                    "role": "ASSISTANT",
                    "content": variables["assistantMessage"],
                    "createdAt": now,
                    "sources": [],
                },
            ]
        else:
            raise AssertionError("Unexpected Core operation in chatbot tests")
        return {
            "data": {
                field: {
                    "conversation": conversation,
                    "userErrors": [],
                }
            }
        }

    counts = {}
    rate_identities = []

    def fake_rate_limiter(identity):
        rate_identities.append(identity)
        counts[identity] = counts.get(identity, 0) + 1
        return 60 if counts[identity] > 10 else None

    monkeypatch.setattr(proxy_module, "_graphql_request", fake_graphql_request)
    monkeypatch.setattr(app, "_chat_rate_limiter", fake_rate_limiter, raising=False)
    with app.test_client() as test_client:
        test_client.core_calls = calls
        test_client.chat_assertion_secret = secret
        test_client.chat_user_ids = user_ids
        test_client.chat_rate_identities = rate_identities
        yield test_client


def create_conversation(client):
    response = client.post(CHAT_CONVERSATIONS)
    assert response.status_code == 201
    body = response.get_json()
    assert isinstance(body, dict)
    assert isinstance(body.get("conversation"), dict)
    conversation_id = body["conversation"].get("id")
    assert isinstance(conversation_id, str) and conversation_id
    return conversation_id


def send_message(client, conversation_id, message):
    return client.post(
        f"{CHAT_CONVERSATIONS}/{conversation_id}/messages",
        json={"message": message},
    )


def assert_chat_error(response, expected_code):
    expected_status = {
        "INVALID_REQUEST": 400,
        "RATE_LIMITED": 429,
        "UNAUTHENTICATED": 401,
        "SERVICE_UNAVAILABLE": 503,
    }[expected_code]
    assert response.status_code == expected_status
    body = response.get_json()
    assert isinstance(body, dict)
    assert set(body) == {"code", "error"}
    assert body["code"] == expected_code
    assert isinstance(body["error"], str) and body["error"]
    assert response.headers.get("Cache-Control") == "no-store"


def assert_chat_reply(response, submitted_text):
    assert response.status_code == 200
    body = response.get_json()
    assert isinstance(body, dict)
    assert set(body) == {
        "conversation_id",
        "answer",
        "sources",
        "recommendations",
        "created_at",
    }
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["sources"], list)
    assert isinstance(body["recommendations"], list)
    assert isinstance(body["created_at"], str) and body["created_at"]
    assert submitted_text not in response.get_data(as_text=True)
    assert response.headers.get("Cache-Control") == "no-store"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Tell me a joke about space.", "I can help"),
        ("Contame un chiste sobre el espacio.", "Puedo ayudar"),
        ("Podes darme la secuencia de Fibonnacci en código Python?", "Puedo ayudar"),
        ("¿Podrías darme un ejemplo de código en Python?", "Puedo ayudar"),
        ("Puedes escribir un programa en Python?", "Puedo ayudar"),
        ("Can you write a poem about juegos?", "I can help"),
        ("Tell me about it.", "Could you clarify"),
        ("Contame más sobre eso.", "¿Podrías aclarar"),
    ],
)
def test_fixed_language_refusal_and_clarification(client, monkeypatch, message, expected):
    conversation_id = create_conversation(client)

    def forbidden():
        pytest.fail("Guarded messages must not create a retrieval/model service")

    monkeypatch.setattr(app_module, "_chatbot_answer_service", None)
    monkeypatch.setattr(app_module.chatbot_answer_service, "create_local_chatbot_service", forbidden)
    response = send_message(client, conversation_id, message)
    assert_chat_reply(response, message)
    assert response.get_json()["answer"].startswith(expected)
    assert len(client.core_calls) == 1


@pytest.mark.parametrize(
    ("message", "answer"),
    [
        ("What payment methods does the store accept?", "The store accepts credit cards."),
        ("¿Qué medios de pago acepta la tienda?", "La tienda acepta tarjetas de crédito."),
    ],
)
def test_faq_questions_reach_grounded_service_in_both_languages(client, monkeypatch, message, answer):
    conversation_id = create_conversation(client)
    queries = []

    class GroundedService:
        def answer(self, query):
            queries.append(query)
            return {"answer": answer, "sources": [{"title": "Approved FAQ"}]}

    monkeypatch.setattr(app_module, "_chatbot_answer_service", GroundedService())
    response = send_message(client, conversation_id, message)
    assert response.status_code == 200
    assert response.get_json()["answer"] == answer
    assert response.get_json()["sources"] == [{"title": "Approved FAQ"}]
    assert queries == [message]
    assert client.core_calls[-1]["variables"]["assistantMessage"] == answer


@pytest.mark.parametrize("message", ["Tengo asma.", "Contame una receta.", "Contame un poema."])
def test_spanish_non_shop_refusals_use_spanish_without_calls(client, message):
    conversation_id = create_conversation(client)
    response = send_message(client, conversation_id, message)
    assert_chat_reply(response, message)
    assert response.get_json()["answer"].startswith(("No puedo", "Puedo ayudar"))
    assert len(client.core_calls) == 1


@pytest.mark.parametrize(
    "details",
    [
        "mi pedido PRIVADO-731",
        "estado del pedido PRIVADO-731",
        "número de pedido PRIVADO-731",
        "seguimiento del pedido PRIVADO-731",
        "mi cuenta PRIVADO-731",
        "contraseña PRIVADO-731",
        "nombre de usuario PRIVADO-731",
        "número de tarjeta PRIVADO-731",
        "ya pagué PRIVADO-731",
        "compré PRIVADO-731",
        "estado del pago PRIVADO-731",
        "estado del reembolso PRIVADO-731",
        "factura de mi compra PRIVADO-731",
        "tengo diabetes PRIVADO-731",
        "vivo en PRIVADO-731",
        "dirección: Calle Falsa 123 PRIVADO-731",
        "DNI 1234567 PRIVADO-731",
    ],
)
def test_spanish_sensitive_shop_messages_stop_before_all_calls(client, monkeypatch, details):
    conversation_id = create_conversation(client)
    message = f"¿Qué medios de pago acepta la tienda? Además, {details}."
    calls = []

    class ForbiddenService:
        def answer(self, query):
            calls.append(query)
            pytest.fail("Protected input reached retrieval/model")

    monkeypatch.setattr(app_module, "_chatbot_answer_service", ForbiddenService())
    assert classify_message(message) == "mixed"
    response = send_message(client, conversation_id, message)
    assert_chat_reply(response, message)
    assert response.get_json()["answer"].startswith("Por favor")
    assert "PRIVADO-731" not in response.get_data(as_text=True)
    assert len(client.core_calls) == 1
    assert not calls
    assert "PRIVADO-731" not in str(client.core_calls)


@pytest.mark.parametrize(
    "message",
    [
        "",
        " \t\n ",
        "OVER_LIMIT_SENTINEL-" + ("x" * 2001),
    ],
    ids=["empty", "whitespace-only", "over-2000-characters"],
)
def test_blank_and_over_limit_messages_return_sanitized_invalid_request(client, message):
    conversation_id = create_conversation(client)

    response = send_message(client, conversation_id, message)

    assert_chat_error(response, "INVALID_REQUEST")
    if message:
        assert message not in response.get_data(as_text=True)
    assert "OVER_LIMIT_SENTINEL" not in response.get_data(as_text=True)
    assert len(client.core_calls) == 1
    assert "recordChatExchange" not in client.core_calls[-1]["query"]


def test_out_of_scope_question_returns_a_safe_chat_reply(client):
    conversation_id = create_conversation(client)
    message = "SPACE_JOKE_SENTINEL: Tell me a joke about space."

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert "SPACE_JOKE_SENTINEL" not in response.get_data(as_text=True)
    assert len(client.core_calls) == 1


def test_mixed_shop_and_order_question_does_not_echo_submitted_text(client):
    conversation_id = create_conversation(client)
    message = (
        "What are your store hours? Also, tell me the status of "
        "synthetic order SYNTHETIC-ORDER-ONLY-731."
    )

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert "SYNTHETIC-ORDER-ONLY-731" not in response.get_data(as_text=True)
    assert "resubmit" in response.get_json()["answer"].lower()
    assert len(client.core_calls) == 1
    assert all(
        "SYNTHETIC-ORDER-ONLY-731" not in str(call)
        for call in client.core_calls
    )


def test_spanish_personal_charge_dispute_is_not_forwarded_persisted_or_echoed(
    client, monkeypatch
):
    conversation_id = create_conversation(client)
    message = "Me cobraron dos veces por el envío, ¿qué hago?"
    calls_before_message = len(client.core_calls)

    def forbidden_answer_service():
        pytest.fail("Protected transactional messages must not reach the answer service")

    monkeypatch.setattr(app_module, "_chatbot_answer_service", None)
    monkeypatch.setattr(
        app_module.chatbot_answer_service,
        "create_local_chatbot_service",
        forbidden_answer_service,
    )

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert "cobraron" not in response.get_data(as_text=True).lower()
    assert classify_message(message) == "mixed"
    assert len(client.core_calls) == calls_before_message
    assert all(message not in str(call) for call in client.core_calls)
    assert all("recordChatExchange" not in call["query"] for call in client.core_calls)


def test_personal_details_are_not_forwarded_or_persisted(client):
    conversation_id = create_conversation(client)
    message = (
        "My email is SYNTHETIC-EMAIL@example.invalid. What are your store hours?"
    )

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert "SYNTHETIC-EMAIL@example.invalid" not in response.get_data(as_text=True)
    assert "resubmit" in response.get_json()["answer"].lower()
    assert len(client.core_calls) == 1


@pytest.mark.parametrize(
    ("message", "sensitive_phrase", "classification"),
    [
        ("What product do you recommend? I have diabetes.", "I have diabetes", "mixed"),
        ("What product do you recommend? I have type 2 diabetes.", "type 2 diabetes", "mixed"),
        ("What game do you recommend? I have asthma.", "I have asthma", "mixed"),
        ("What game should I buy? I was diagnosed with asthma.", "diagnosed with asthma", "mixed"),
        ("What product do you recommend? I HAVE DIABETES.", "I HAVE DIABETES", "mixed"),
        ("I have diabetes.", "I have diabetes", "protected"),
    ],
)
def test_health_disclosures_are_not_forwarded_persisted_or_echoed(
    client, message, sensitive_phrase, classification
):
    conversation_id = create_conversation(client)
    calls_before_message = len(client.core_calls)

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert sensitive_phrase.lower() not in response.get_data(as_text=True).lower()
    assert len(client.core_calls) == calls_before_message
    assert classify_message(message) == classification


def test_recommendation_without_health_disclosure_is_in_scope(client):
    conversation_id = create_conversation(client)
    message = "What product do you recommend? I have a game night planned."

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert classify_message(message) == "in_scope"
    assert len(client.core_calls) == 2
    assert "recordChatExchange" in client.core_calls[-1]["query"]
    assert client.core_calls[-1]["variables"]["userMessage"] == message


def test_unclear_topic_gets_a_safe_chat_reply_without_echoing_input(client):
    conversation_id = create_conversation(client)
    message = "UNCLEAR_TOPIC_SENTINEL: Tell me about it."

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert "UNCLEAR_TOPIC_SENTINEL" not in response.get_data(as_text=True)
    assert "store-related" in response.get_json()["answer"].lower()
    assert len(client.core_calls) == 1


def test_rate_limit_allows_ten_chat_endpoint_requests_per_session(client):
    # The OpenAPI describes one shared limit across chatbot endpoints. Creating
    # the conversation is therefore the first request in this browser session.
    conversation_id = create_conversation(client)
    safe_out_of_scope_message = "Tell me a joke about space."

    for _ in range(9):
        response = send_message(client, conversation_id, safe_out_of_scope_message)
        assert_chat_reply(response, safe_out_of_scope_message)

    limited_response = send_message(
        client, conversation_id, safe_out_of_scope_message
    )
    assert_chat_error(limited_response, "RATE_LIMITED")
    retry_after = limited_response.headers.get("Retry-After")
    assert retry_after is not None
    assert retry_after.isdigit()
    assert int(retry_after) >= 1


def test_in_scope_message_uses_fresh_assertion_and_only_core_persists_exchange(client):
    conversation_id = create_conversation(client)
    cookie = client.get_cookie("chat_session")
    assert cookie is not None
    message = "What is your return policy?"

    response = send_message(client, conversation_id, message)

    assert_chat_reply(response, message)
    assert "return policy" not in response.get_json()["answer"].lower()
    assert len(client.core_calls) == 2
    create_call, record_call = client.core_calls
    assert "createChatConversation" in create_call["query"]
    assert "recordChatExchange" in record_call["query"]
    assert record_call["variables"]["userMessage"] == message
    assert record_call["variables"]["assistantMessage"] == response.get_json()["answer"]
    assertions = [call["headers"]["X-Chat-Assertion"] for call in client.core_calls]
    decoded = [
        jwt.decode(
            assertion,
            client.chat_assertion_secret,
            algorithms=["HS256"],
            audience="bgg-shop-core",
            issuer="bgg-shop-bff",
        )
        for assertion in assertions
    ]
    assert decoded[0]["sub"] == hashlib.sha256(cookie.value.encode()).hexdigest()
    assert decoded[0]["scope"] == "chat:conversations"
    assert decoded[0]["exp"] - decoded[0]["iat"] == 60
    assert decoded[1]["sub"] == decoded[0]["sub"]
    assert assertions[0] != assertions[1]


def test_anonymous_cookie_is_session_only_and_browser_assertion_is_ignored(client):
    response = client.post(
        CHAT_CONVERSATIONS,
        headers={"X-Chat-Assertion": "browser-supplied-assertion"},
    )

    assert response.status_code == 201
    cookie_header = response.headers["Set-Cookie"]
    assert "chat_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=Lax" in cookie_header
    if app.config["CHAT_SESSION_COOKIE_SECURE"]:
        assert "Secure" in cookie_header
    else:
        assert "Secure" not in cookie_header
    assert "Max-Age=" not in cookie_header
    assert "Expires=" not in cookie_header
    assert client.core_calls[0]["headers"]["X-Chat-Assertion"] != (
        "browser-supplied-assertion"
    )


def test_bearer_auth_is_authoritative_and_does_not_use_anonymous_assertion(client):
    bearer = "Bearer " + secrets.token_urlsafe(24)
    client.chat_user_ids[bearer] = "registered-user-123"
    cookie = secrets.token_urlsafe(32)
    client.set_cookie("chat_session", cookie)

    response = client.post(
        CHAT_CONVERSATIONS,
        headers={
            "Authorization": bearer,
            "X-Chat-Assertion": "browser-supplied-assertion",
        },
    )

    assert response.status_code == 201
    assert "Set-Cookie" not in response.headers
    assert client.core_calls[0]["token"] == bearer
    assert "X-Chat-Assertion" not in client.core_calls[0]["headers"]
    assert client.chat_rate_identities == ["chat:user:registered-user-123"]


def test_missing_anonymous_assertion_secret_fails_closed(client, monkeypatch):
    monkeypatch.setenv("CHAT_ASSERTION_SECRET", "")

    response = client.post(CHAT_CONVERSATIONS)

    assert_chat_error(response, "SERVICE_UNAVAILABLE")
    assert len(client.core_calls) == 0


def test_rate_limit_backend_failure_fails_closed(client, monkeypatch):
    def unavailable_limiter(identity):
        raise RuntimeError("REDIS_FAILURE_SENTINEL")

    monkeypatch.setattr(app, "_chat_rate_limiter", unavailable_limiter)

    response = client.post(CHAT_CONVERSATIONS)

    assert_chat_error(response, "SERVICE_UNAVAILABLE")
    assert "REDIS_FAILURE_SENTINEL" not in response.get_data(as_text=True)
    assert len(client.core_calls) == 0


def test_authenticated_rate_limit_uses_core_stable_user_id_across_endpoints(client):
    token_one = "Bearer synthetic-token-one"
    token_two = "Bearer synthetic-token-two"
    other_user_token = "Bearer synthetic-token-other"
    client.chat_user_ids.update(
        {
            token_one: "core-user-123",
            token_two: "core-user-123",
            other_user_token: "core-user-456",
        }
    )

    create_response = client.post(
        CHAT_CONVERSATIONS, headers={"Authorization": token_one}
    )
    assert create_response.status_code == 201
    conversation_id = create_response.get_json()["conversation"]["id"]

    for _ in range(9):
        response = client.post(
            f"{CHAT_CONVERSATIONS}/{conversation_id}/messages",
            headers={"Authorization": token_two},
            json={"message": "Tell me a joke about space."},
        )
        assert response.status_code == 200

    other_user_response = client.post(
        f"{CHAT_CONVERSATIONS}/{conversation_id}/messages",
        headers={"Authorization": other_user_token},
        json={"message": "Tell me a joke about space."},
    )
    assert other_user_response.status_code == 200

    exhausted_response = client.post(
        f"{CHAT_CONVERSATIONS}/{conversation_id}/messages",
        headers={"Authorization": token_one},
        json={"message": "Tell me a joke about space."},
    )

    assert_chat_error(exhausted_response, "RATE_LIMITED")
    assert client.chat_rate_identities[:10] == ["chat:user:core-user-123"] * 10
    assert client.chat_rate_identities[10:] == [
        "chat:user:core-user-456",
        "chat:user:core-user-123",
    ]
    identity_lookups = [
        call for call in client.core_calls if "me { id }" in call["query"]
    ]
    assert len(identity_lookups) == 12
    assert all(call["variables"] == {} for call in identity_lookups)
    assert all(
        call["token"] in {token_one, token_two, other_user_token}
        for call in identity_lookups
    )
    assert all(
        "Tell me a joke about space." not in call["query"]
        for call in identity_lookups
    )
    assert all(
        token not in identity
        for token in (token_one, token_two, other_user_token)
        for identity in client.chat_rate_identities
    )
    assert not any(
        "recordChatExchange" in call["query"] for call in client.core_calls
    )


def test_invalid_core_user_identity_does_not_fall_back_to_cookie(client):
    token = "Bearer synthetic-token-without-core-user"
    cookie = "c" * 48
    client.chat_user_ids[token] = None
    client.set_cookie("chat_session", cookie)

    response = client.post(
        CHAT_CONVERSATIONS, headers={"Authorization": token}
    )

    assert_chat_error(response, "UNAUTHENTICATED")
    assert len(client.core_calls) == 1
    assert "me { id }" in client.core_calls[0]["query"]
    assert client.core_calls[0]["token"] == token
    assert client.chat_rate_identities == []
    assert "Set-Cookie" not in response.headers


def test_malformed_bearer_does_not_fall_back_to_cookie(client):
    client.set_cookie("chat_session", "d" * 48)

    response = client.post(
        CHAT_CONVERSATIONS, headers={"Authorization": "Basic synthetic-token"}
    )

    assert_chat_error(response, "UNAUTHENTICATED")
    assert client.core_calls == []
    assert client.chat_rate_identities == []


def test_authenticated_identity_lookup_failure_is_sanitized_and_fails_closed(
    client, monkeypatch
):
    calls = []

    def failing_identity_lookup(query, variables, token=None, **kwargs):
        calls.append(
            {"query": query, "variables": variables, "token": token}
        )
        raise RuntimeError("IDENTITY_LOOKUP_FAILURE_SENTINEL")

    monkeypatch.setattr(proxy_module, "_graphql_request", failing_identity_lookup)
    token = "Bearer synthetic-token"

    response = client.post(
        CHAT_CONVERSATIONS, headers={"Authorization": token}
    )

    assert_chat_error(response, "SERVICE_UNAVAILABLE")
    assert "IDENTITY_LOOKUP_FAILURE_SENTINEL" not in response.get_data(as_text=True)
    assert len(calls) == 1
    assert "me { id }" in calls[0]["query"]
    assert calls[0]["variables"] == {}
    assert calls[0]["token"] == token
    assert client.chat_rate_identities == []


def test_anonymous_rate_limit_identity_uses_only_validated_session_cookie(client):
    first_response = client.post(CHAT_CONVERSATIONS)
    assert first_response.status_code == 201
    first_cookie = client.get_cookie("chat_session").value

    second_cookie = "e" * 48
    client.set_cookie("chat_session", second_cookie)
    second_response = client.post(CHAT_CONVERSATIONS)
    assert second_response.status_code == 201

    expected_identities = [
        "chat:session:"
        + hashlib.sha256(f"chat:session:{cookie}".encode("utf-8")).hexdigest()
        for cookie in (first_cookie, second_cookie)
    ]
    assert client.chat_rate_identities == expected_identities
    assert first_cookie not in client.chat_rate_identities[0]
    assert second_cookie not in client.chat_rate_identities[1]
    assert len(set(client.chat_rate_identities)) == 2
    assert all(call.get("token") is None for call in client.core_calls)


def test_invalid_anonymous_cookie_is_rejected_before_rate_limiting(client):
    client.set_cookie("chat_session", "invalid-cookie")

    response = client.post(CHAT_CONVERSATIONS)

    assert_chat_error(response, "UNAUTHENTICATED")
    assert client.chat_rate_identities == []
    assert client.core_calls == []


def test_in_scope_core_failure_is_sanitized(client, monkeypatch):
    conversation_id = create_conversation(client)
    monkeypatch.setattr(
        proxy_module,
        "_graphql_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            proxy_module.UpstreamError("INTERNAL_UPSTREAM_SENTINEL")
        ),
    )

    response = send_message(client, conversation_id, "What are your store hours?")

    assert_chat_error(response, "SERVICE_UNAVAILABLE")
    assert "INTERNAL_UPSTREAM_SENTINEL" not in response.get_data(as_text=True)
