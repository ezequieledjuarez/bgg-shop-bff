"""Black-box catalog recommendation tests for the buyer chatbot."""

from dataclasses import dataclass, field
import secrets

import pytest
import requests

import app as app_module
from app import app
from src import proxy as proxy_module
from src.chatbot import rag as rag_module
from src.controllers import chatbot_controller


CHAT_CONVERSATIONS = "/api/v1/chat/conversations"
CATALOG_SENTINEL = "Synthetic live catalog item ZXQ-481"
UPSTREAM_SENTINEL = "UPSTREAM_INTERNAL_SENTINEL"

PRODUCT = {
    "bgg_id": 274364,
    "name": CATALOG_SENTINEL,
    "release_year": 2019,
    "min_players": 2,
    "max_players": 2,
    "playing_time_minutes": 60,
    "min_age": 12,
    "weight": 2.25,
    "category": ["Juegos de Estrategia"],
    "price": 4800.0,
    "publisher": "Synthetic Publisher",
    "image_url": "/media/synthetic-zxq-481.webp",
    "quantity": 3,
}

_GRAPHQL_PRODUCT_FIELDS = {
    "bgg_id": "bggId",
    "release_year": "releaseYear",
    "min_players": "minPlayers",
    "max_players": "maxPlayers",
    "playing_time_minutes": "playingTimeMinutes",
    "min_age": "minAge",
    "image_url": "imageUrl",
}


class FakeCoreResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"Core returned {self.status_code}")

    def json(self):
        return self.payload


class FakeCoreTransport:
    """In-memory GraphQL transport; it cannot reach Core or another service."""

    def __init__(self):
        self.calls = []
        self.events = []
        self.products = [PRODUCT]
        self.catalog_error = False

    def post(self, url, json=None, **kwargs):
        query = json["query"]
        variables = json.get("variables", {})
        self.calls.append({"url": url, "query": query, "variables": variables})

        if "query Products(" in query:
            self.events.append("catalog")
            if self.catalog_error:
                raise requests.ConnectionError(
                    f"{UPSTREAM_SENTINEL} at http://core.internal/graphql"
                )
            products = [
                {
                    _GRAPHQL_PRODUCT_FIELDS.get(key, key): value
                    for key, value in product.items()
                }
                for product in self.products
            ]
            return FakeCoreResponse(
                {
                    "data": {
                        "products": {
                            "items": products,
                            "page": 1,
                            "pageSize": 50,
                            "total": len(products),
                            "totalPages": 1 if products else 0,
                        }
                    }
                }
            )

        now = "2026-11-07T08:00:00+00:00"
        conversation = {
            "id": "00000000-0000-4000-8000-000000000013",
            "messages": [],
            "createdAt": now,
            "updatedAt": now,
            "expiresAt": "2026-12-07T08:00:00+00:00",
        }
        if "createChatConversation" in query:
            field_name = "createChatConversation"
        elif "recordChatExchange" in query:
            self.events.append("record")
            field_name = "recordChatExchange"
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
            raise AssertionError(f"Unexpected fake Core operation: {query}")

        return FakeCoreResponse(
            {
                "data": {
                    field_name: {
                        "conversation": conversation,
                        "userErrors": [],
                    }
                }
            }
        )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.config, "TESTING", True)
    monkeypatch.setattr(app_module, "_append_incoming_log", lambda entry: None)
    monkeypatch.setenv("CHAT_ASSERTION_SECRET", secrets.token_urlsafe(48))
    transport = FakeCoreTransport()
    monkeypatch.setattr(proxy_module.requests, "post", transport.post)

    counts = {}

    def allow_requests(identity):
        counts[identity] = counts.get(identity, 0) + 1
        return None

    monkeypatch.setattr(app, "_chat_rate_limiter", allow_requests, raising=False)
    with app.test_client() as test_client:
        test_client.fake_core = transport
        yield test_client


def create_conversation(client):
    response = client.post(CHAT_CONVERSATIONS)
    assert response.status_code == 201
    return response.get_json()["conversation"]["id"]


def send_message(client, conversation_id, message):
    return client.post(
        f"{CHAT_CONVERSATIONS}/{conversation_id}/messages",
        json={"message": message},
    )


def _product_query_calls(transport):
    return [
        call
        for call in transport.calls
        if "query Products(" in call["query"]
    ]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Recommend games for 2 players under 5000 pesos, category: Juegos de Estrategia", "Here are current products"),
        ("Recomendame juegos de estrategia para 2 jugadores por menos de 5000 pesos", "Estos son los productos"),
        ("Recomiéndame juegos de estrategia para dos jugadores por menos de 5000 pesos", "Estos son los productos"),
    ],
)
def test_fixed_language_catalog_recommendation(client, message, expected):
    conversation_id = create_conversation(client)
    response = send_message(client, conversation_id, message)
    assert response.status_code == 200
    assert response.get_json()["answer"].startswith(expected)
    assert response.get_json()["recommendations"] == [PRODUCT]
    filters = _product_query_calls(client.fake_core)[0]["variables"]
    assert filters["minPlayers"] == filters["maxPlayers"] == 2
    assert filters["priceMax"] == 5000
    assert filters["categoryName"] == "Juegos de Estrategia"
    assert {key for key, value in filters.items() if value is not None} <= {
        "minPlayers", "maxPlayers", "priceMin", "priceMax", "categoryName", "page", "pageSize"
    }


@pytest.mark.parametrize(
    "message",
    [
        "Recomendame juegos para 2 jugadores que duren 30 minutos",
        "Recomendame juegos con duración de 30 minutos",
        "Recomendame juegos en idioma español",
        "Recomendame juegos para niños de 5 años",
        "Recomendame juegos con dificultad baja",
    ],
)
def test_spanish_unsupported_catalog_filters_clarify_without_catalog_calls(client, message):
    conversation_id = create_conversation(client)
    response = send_message(client, conversation_id, message)
    assert response.status_code == 200
    assert response.get_json()["answer"].startswith("No puedo filtrar")
    assert response.get_json()["recommendations"] == []
    assert not _product_query_calls(client.fake_core)


@pytest.mark.parametrize(
    ("message", "expected_prefix"),
    [
        ("Recommend games for children", "I can't filter"),
        ("Recommend games for kids", "I can't filter"),
        ("Recomendame juegos para niños", "No puedo filtrar"),
        ("Recomendame juegos para niñas", "No puedo filtrar"),
    ],
)
def test_unsupported_audience_catalog_filters_clarify_in_query_language_without_catalog_calls(
    client, message, expected_prefix
):
    conversation_id = create_conversation(client)

    response = send_message(client, conversation_id, message)

    assert response.status_code == 200
    body = response.get_json()
    assert body["answer"].startswith(expected_prefix)
    assert body["recommendations"] == []
    assert not _product_query_calls(client.fake_core)


@pytest.mark.parametrize("catalog", [False, True])
def test_spanish_unavailable_reply_is_sanitized_and_not_persisted(client, monkeypatch, catalog):
    conversation_id = create_conversation(client)

    class Unavailable:
        def answer(self, query):
            raise RuntimeError(f"{UPSTREAM_SENTINEL} at http://core.internal/graphql")

    monkeypatch.setattr(app_module, "_chatbot_answer_service", Unavailable())
    client.fake_core.catalog_error = catalog
    message = "Recomendame juegos para 2 jugadores" if catalog else "¿Qué medios de pago acepta la tienda?"
    response = send_message(client, conversation_id, message)
    assert response.status_code == 503
    assert response.get_json() == {
        "code": "SERVICE_UNAVAILABLE",
        "error": "El chat no está disponible temporalmente. Inténtalo de nuevo.",
    }
    assert "record" not in client.fake_core.events
    assert UPSTREAM_SENTINEL not in response.get_data(as_text=True)
    assert "core.internal" not in response.get_data(as_text=True)


def test_recommendations_match_exact_current_core_products_and_supported_facts(
    client, monkeypatch
):
    conversation_id = create_conversation(client)
    events = client.fake_core.events
    classify = chatbot_controller.classify_message

    def classify_and_record_guardrail(message):
        events.append("guardrail")
        return classify(message)

    monkeypatch.setattr(
        chatbot_controller, "classify_message", classify_and_record_guardrail
    )
    message = (
        "What product do you recommend? I have a game night planned and want "
        "Juegos de Estrategia for exactly two players under 5000 pesos."
    )

    response = send_message(client, conversation_id, message)

    assert response.status_code == 200
    body = response.get_json()
    assert body["recommendations"] == [PRODUCT]
    assert body["conversation_id"] == conversation_id
    assert CATALOG_SENTINEL in response.get_data(as_text=True)
    calls = _product_query_calls(client.fake_core)
    assert len(calls) == 1
    filters = calls[0]["variables"]
    assert filters["minPlayers"] == 2
    assert filters["maxPlayers"] == 2
    assert filters["categoryName"] == "Juegos de Estrategia"
    assert filters["priceMax"] == 5000
    assert "playingTimeMinutes" not in filters
    assert "guardrail" in events
    assert "catalog" in events
    assert events.index("guardrail") < events.index("catalog")


def test_unsupported_playing_time_filter_is_clarified_without_invented_core_filter(
    client,
):
    conversation_id = create_conversation(client)
    message = (
        "What product do you recommend? I have a game night planned and want "
        "a game that takes 30 minutes or less."
    )

    response = send_message(client, conversation_id, message)

    assert response.status_code == 200
    body = response.get_json()
    answer = body["answer"].lower()
    assert body["recommendations"] == []
    assert "playingTimeMinutes" not in str(client.fake_core.calls)
    assert not _product_query_calls(client.fake_core)
    assert any(
        word in answer
        for word in ("clarify", "can't filter", "cannot filter", "not supported", "limitation")
    )


def test_no_matching_catalog_products_returns_explicit_empty_result(client):
    client.fake_core.products = []
    conversation_id = create_conversation(client)
    message = "What product do you recommend? I have a game night planned."

    response = send_message(client, conversation_id, message)

    assert response.status_code == 200
    body = response.get_json()
    assert body["recommendations"] == []
    assert CATALOG_SENTINEL not in response.get_data(as_text=True)
    answer = body["answer"].lower()
    assert any(
        phrase in answer
        for phrase in ("no matching", "no products", "couldn't find", "could not find")
    )


def test_catalog_upstream_failure_is_sanitized_and_does_not_persist_exchange(client):
    client.fake_core.catalog_error = True
    conversation_id = create_conversation(client)
    message = "What product do you recommend? I have a game night planned."

    response = send_message(client, conversation_id, message)

    assert response.status_code == 503
    body = response.get_json()
    assert body["code"] == "SERVICE_UNAVAILABLE"
    assert UPSTREAM_SENTINEL not in response.get_data(as_text=True)
    assert "core.internal" not in response.get_data(as_text=True)
    assert "record" not in client.fake_core.events


def test_out_of_scope_guardrail_runs_before_any_catalog_query(client, monkeypatch):
    conversation_id = create_conversation(client)
    classify = chatbot_controller.classify_message
    classifications = []

    def classify_and_record(message):
        classifications.append(message)
        return classify(message)

    monkeypatch.setattr(chatbot_controller, "classify_message", classify_and_record)
    response = send_message(client, conversation_id, "Tell me a joke about space.")

    assert response.status_code == 200
    assert classifications == ["Tell me a joke about space."]
    assert not _product_query_calls(client.fake_core)
    assert "record" not in client.fake_core.events
    assert "Tell me a joke about space." not in response.get_data(as_text=True)


@dataclass
class FakeDocument:
    page_content: str
    metadata: dict = field(default_factory=dict)


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[float(index)] for index, _ in enumerate(texts)]

    def embed_query(self, text):
        return [float(len(text))]


class FakeVectorStore:
    """In-memory index stand-in; never creates a ChromaDB client or disk index."""

    def __init__(self):
        self.documents_by_id = {}

    def get(self, include=None):
        entries = list(self.documents_by_id.items())
        return {
            "ids": [document_id for document_id, _ in entries],
            "documents": [document.page_content for _, document in entries],
            "metadatas": [document.metadata for _, document in entries],
        }

    def add_documents(self, documents, ids=None):
        for document_id, document in zip(ids or (), documents):
            self.documents_by_id[document_id] = document

    def update_documents(self, ids, documents):
        self.add_documents(documents, ids=ids)

    def delete(self, ids):
        for document_id in ids:
            self.documents_by_id.pop(document_id, None)


class FakeRetriever:
    def invoke(self, query):
        return []


class FakeProvider:
    def invoke(self, prompt):
        return "Synthetic FAQ response."


def test_live_catalog_results_never_enter_approved_chromadb_corpus(
    client, tmp_path
):
    approved_sources = tmp_path / "approved"
    approved_sources.mkdir()
    (approved_sources / "store-faq.md").write_text(
        "---\ntitle: Store FAQ\napproved: true\nstatus: active\n"
        "url: https://shop.example/faq\n---\n"
        "# Store FAQ\nContact the store for general questions.\n",
        encoding="utf-8",
    )
    vector_store = FakeVectorStore()
    rag = rag_module.ApprovedFaqRag(
        approved_sources_dir=approved_sources,
        embeddings=FakeEmbeddings(),
        vector_store=vector_store,
        retriever=FakeRetriever(),
        llm=FakeProvider(),
    )
    assert rag.ingest_approved_sources() == 1
    indexed_before_request = vector_store.get()
    conversation_id = create_conversation(client)

    response = send_message(
        client,
        conversation_id,
        "What product do you recommend? I have a game night planned.",
    )

    assert response.status_code == 200
    assert CATALOG_SENTINEL in response.get_data(as_text=True)
    assert vector_store.get() == indexed_before_request
    indexed_text = "\n".join(vector_store.get()["documents"])
    assert CATALOG_SENTINEL not in indexed_text
    assert all(
        metadata["source"].startswith(str(approved_sources.resolve()))
        for metadata in vector_store.get()["metadatas"]
    )
