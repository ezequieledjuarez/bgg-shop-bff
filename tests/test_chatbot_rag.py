"""Deterministic tests for the approved FAQ retrieval boundary."""

from dataclasses import dataclass, field
from pathlib import Path
import sys
import shutil
from types import SimpleNamespace

import pytest

from src.chatbot.provider import LocalProviderError, OllamaChatProvider
from src.chatbot.rag import ApprovedFaqRag, FALLBACK_RESPONSE, SPANISH_FALLBACK_RESPONSE
from src.chatbot.service import ChatbotServiceUnavailable, GroundedAnswerService


FAQ_SOURCE = Path(__file__).parents[1] / "knowledge" / "approved" / "store-faq.md"
CATALOG_MARKER = "synthetic catalog-only title ZXQ-481 with price 987654"
CONVERSATION_MARKER = "synthetic private conversation marker PII-204"


@dataclass
class FakeDocument:
    page_content: str
    metadata: dict = field(default_factory=dict)


class FakeEmbeddings:
    def __init__(self):
        self.embedded_documents = []

    def embed_documents(self, texts):
        self.embedded_documents.extend(texts)
        return [[float(index)] for index, _ in enumerate(texts)]

    def embed_query(self, text):
        return [float(len(text))]


class FakeVectorStore:
    """In-memory stand-in; never creates a ChromaDB client or disk index."""

    def __init__(self, embeddings):
        self.embeddings = embeddings
        self.documents = []
        self._documents_by_id = {}
        self.add_calls = 0
        self.update_calls = 0

    def add_documents(self, documents, ids=None):
        self.add_calls += 1
        if ids is None:
            self.documents.extend(documents)
        else:
            self._documents_by_id.update(zip(ids, documents))
            self.documents = list(self._documents_by_id.values())
        self.embeddings.embed_documents(
            [document.page_content for document in documents]
        )

    def get(self, include=None):
        return {
            "ids": list(self._documents_by_id),
            "documents": [
                document.page_content for document in self._documents_by_id.values()
            ],
            "metadatas": [
                document.metadata for document in self._documents_by_id.values()
            ],
        }

    def update_documents(self, ids, documents):
        self.update_calls += 1
        self._documents_by_id.update(zip(ids, documents))
        self.documents = list(self._documents_by_id.values())
        self.embeddings.embed_documents(
            [document.page_content for document in documents]
        )

    def delete(self, ids):
        for document_id in ids:
            self._documents_by_id.pop(document_id, None)
        self.documents = list(self._documents_by_id.values())


class FakeRetriever:
    def __init__(self, documents=()):
        self.documents = list(documents)
        self.queries = []

    def invoke(self, query):
        self.queries.append(query)
        return list(self.documents)


class FakeLLMProvider:
    """Captures model input and returns a deterministic synthetic completion."""

    def __init__(self, response="Podés pagar con tarjetas de débito y crédito."):
        self.response = response
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.response


def _service(tmp_path, documents=(), llm_response=None):
    knowledge = tmp_path / "knowledge"
    approved = knowledge / "approved"
    approved.mkdir(parents=True)
    shutil.copyfile(FAQ_SOURCE, approved / "store-faq.md")

    # These synthetic inputs must never be treated as approved corpus sources.
    (knowledge / "drafts").mkdir()
    (knowledge / "drafts" / "draft.md").write_text(CATALOG_MARKER)
    conversations = tmp_path / "conversation-content"
    conversations.mkdir()
    (conversations / "transcript.txt").write_text(CONVERSATION_MARKER)
    catalog = tmp_path / "dynamic-catalog"
    catalog.mkdir()
    (catalog / "core-result.json").write_text(CATALOG_MARKER)

    embeddings = FakeEmbeddings()
    vector_store = FakeVectorStore(embeddings)
    retriever = FakeRetriever(documents)
    llm = FakeLLMProvider()
    if llm_response is not None:
        llm.response = llm_response
    for document in documents:
        document.metadata.setdefault(
            "source", str(approved / "store-faq.md")
        )
    service = ApprovedFaqRag(
        approved_sources_dir=approved,
        embeddings=embeddings,
        vector_store=vector_store,
        retriever=retriever,
        llm=llm,
    )
    return service, embeddings, vector_store, retriever, llm


def _approved_document(content, *, title="Preguntas Frecuentes", url=None):
    metadata = {"title": title, "approved": True, "status": "active"}
    if url is not None:
        metadata["url"] = url
    return FakeDocument(content, metadata)


@pytest.mark.parametrize(
    ("question", "language", "answer"),
    [
        ("What payment methods does the store accept?", "English", "The store accepts debit and credit cards."),
        ("¿Qué medios de pago acepta la tienda?", "Spanish", "La tienda acepta tarjetas de débito y crédito."),
    ],
)
def test_fixed_language_grounded_faq(tmp_path, question, language, answer):
    document = _approved_document("La tienda acepta tarjetas de débito y crédito.")
    service, _, _, retriever, llm = _service(tmp_path, [document], answer)
    result = service.answer(question)
    assert result["answer"] == answer
    assert result["sources"] == [{"title": "Preguntas Frecuentes"}]
    assert retriever.queries == [question]
    assert f"Answer in {language}" in llm.prompts[0]
    assert "using only the approved" in llm.prompts[0]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What payment methods does the store accept?", "I can’t answer with confidence"),
        ("¿Qué medios de pago acepta la tienda?", "No puedo responder con confianza"),
    ],
)
@pytest.mark.parametrize("empty_completion", [False, True])
def test_fixed_language_uncertainty_fallback(tmp_path, question, expected, empty_completion):
    documents = [_approved_document("Aceptamos tarjetas de débito.")] if empty_completion else []
    service, _, _, _, llm = _service(tmp_path, documents, "")
    result = service.answer(question)
    assert result["answer"].startswith(expected)
    assert result["sources"] == []
    assert bool(llm.prompts) == empty_completion


def test_ingestion_indexes_only_approved_static_faq(tmp_path):
    service, embeddings, vector_store, _, _ = _service(tmp_path)

    service.ingest_approved_sources()

    indexed_content = "\n".join(
        document.page_content for document in vector_store.documents
    )
    assert vector_store.documents
    assert "tarjetas de débito y crédito" in indexed_content
    assert vector_store.documents[0].metadata["url"] == "http://localhost:3030"
    assert CATALOG_MARKER not in indexed_content
    assert CONVERSATION_MARKER not in indexed_content
    assert all(
        Path(document.metadata["source"]).resolve().is_relative_to(
            (tmp_path / "knowledge" / "approved").resolve()
        )
        for document in vector_store.documents
    )
    assert CATALOG_MARKER not in "\n".join(embeddings.embedded_documents)
    assert CONVERSATION_MARKER not in "\n".join(embeddings.embedded_documents)


def test_ingestion_updates_existing_source_without_duplicate_documents(tmp_path):
    service, _, vector_store, _, _ = _service(tmp_path)
    service.ingest_approved_sources()
    initial_add_calls = vector_store.add_calls
    approved_file = tmp_path / "knowledge" / "approved" / "store-faq.md"
    approved_file.write_text("# Updated FAQ\n\nUpdated approved answer.")

    service.ingest_approved_sources()

    assert vector_store.add_calls == initial_add_calls
    assert vector_store.update_calls == 1
    assert len(vector_store.documents) == 1
    assert vector_store.documents[0].page_content == (
        "# Updated FAQ\n\nUpdated approved answer."
    )


def test_ingestion_does_not_reembed_unchanged_sources(tmp_path):
    service, embeddings, vector_store, _, _ = _service(tmp_path)
    service.ingest_approved_sources()
    initial_add_calls = vector_store.add_calls
    initial_embedding_count = len(embeddings.embedded_documents)

    service.ingest_approved_sources()

    assert vector_store.add_calls == initial_add_calls
    assert len(embeddings.embedded_documents) == initial_embedding_count


def test_ingestion_withdrawal_removes_previously_indexed_source(tmp_path):
    service, _, vector_store, _, _ = _service(tmp_path)
    service.ingest_approved_sources()
    approved_file = tmp_path / "knowledge" / "approved" / "store-faq.md"
    approved_file.write_text(
        "---\napproved: false\nstatus: withdrawn\n---\n"
        "# Withdrawn FAQ\n\nThis answer must no longer be indexed."
    )

    service.ingest_approved_sources()

    assert vector_store.documents == []


def test_ingestion_removes_deleted_approved_sources(tmp_path):
    service, _, vector_store, _, _ = _service(tmp_path)
    service.ingest_approved_sources()
    (tmp_path / "knowledge" / "approved" / "store-faq.md").unlink()

    service.ingest_approved_sources()

    assert vector_store.documents == []


def test_ingestion_removes_index_entries_outside_approved_sources(tmp_path):
    service, _, vector_store, _, _ = _service(tmp_path)
    vector_store._documents_by_id["unapproved"] = FakeDocument(
        CATALOG_MARKER,
        {
            "title": "Dynamic catalog",
            "source": str(tmp_path / "dynamic-catalog" / "core-result.json"),
            "approved": True,
            "status": "active",
        },
    )
    vector_store.documents = list(vector_store._documents_by_id.values())

    service.ingest_approved_sources()

    assert all(
        CATALOG_MARKER not in document.page_content
        for document in vector_store.documents
    )


def test_answer_is_grounded_in_retrieved_faq_and_attributes_its_source(tmp_path):
    faq = _approved_document(
        "Se puede pagar con tarjetas de débito y crédito.",
        url="http://localhost:3000",
    )
    service, _, _, retriever, llm = _service(
        tmp_path, documents=[faq]
    )
    service.ingest_approved_sources()

    result = service.answer("¿Qué formas de pago aceptan?")

    assert result["answer"] == llm.response
    assert result["sources"] == [
        {"title": "Preguntas Frecuentes", "url": "http://localhost:3000"}
    ]
    assert retriever.queries == ["¿Qué formas de pago aceptan?"]
    assert "tarjetas de débito y crédito" in str(llm.prompts[0])


@pytest.mark.parametrize(
    "query,relevant_content,unrelated_content",
    [
        pytest.param(
            "What payment methods are accepted?",
            "Payments are debit and credit cards.",
            "Shipping takes three days.",
            id="topic-relevance",
        ),
        pytest.param(
            "What are your opening hours?",
            "Opening hours are nine to five.",
            "Shipping takes three days.",
            id="keyword-relevance",
        ),
    ],
)
def test_relevant_hit_does_not_allow_unrelated_prompts_or_sources(
    tmp_path, query, relevant_content, unrelated_content
):
    relevant = _approved_document(relevant_content, title="Relevant FAQ")
    unrelated = _approved_document(
        unrelated_content, title="Unrelated FAQ", url="http://localhost:3030/other"
    )
    service, _, _, _, llm = _service(
        tmp_path, documents=[unrelated, relevant], llm_response="Grounded answer."
    )

    result = service.answer(query)

    assert result == {
        "answer": llm.response,
        "sources": [{"title": "Relevant FAQ"}],
    }
    assert len(llm.prompts) == 1
    assert relevant_content in llm.prompts[0]
    assert unrelated_content not in llm.prompts[0]
    assert "Unrelated FAQ" not in llm.prompts[0]


def test_unrelated_conflicts_do_not_block_relevant_answer(tmp_path):
    relevant = _approved_document(
        "Shipping takes three days.", title="Shipping FAQ"
    )
    service, _, _, _, llm = _service(
        tmp_path,
        documents=[
            _approved_document("Payments are debit-card only.", title="FAQ A"),
            relevant,
            _approved_document("Payments include credit cards too.", title="FAQ B"),
        ],
        llm_response="Shipping takes three days.",
    )

    result = service.answer("How long does shipping take?")

    assert result == {
        "answer": llm.response,
        "sources": [{"title": "Shipping FAQ"}],
    }
    assert len(llm.prompts) == 1
    assert relevant.page_content in llm.prompts[0]
    assert "Payments" not in llm.prompts[0]


@pytest.mark.parametrize(
    "documents",
    [
        pytest.param([], id="insufficient-evidence"),
        pytest.param(
            [_approved_document("Shipping takes three days.")],
            id="irrelevant-evidence",
        ),
        pytest.param(
            [
                FakeDocument(
                    "A stale answer.",
                    {"title": "Old FAQ", "approved": True, "status": "stale"},
                )
            ],
            id="stale-evidence",
        ),
        pytest.param(
            [
                FakeDocument(
                    "A withdrawn answer.",
                    {"title": "Withdrawn FAQ", "approved": True, "status": "withdrawn"},
                )
            ],
            id="withdrawn-evidence",
        ),
        pytest.param(
            [
                _approved_document("Payments are debit-card only.", title="FAQ A"),
                _approved_document(
                    "Payments include credit cards too.", title="FAQ B"
                ),
            ],
            id="conflicting-evidence",
        ),
    ],
)
def test_unsupported_or_untrustworthy_evidence_uses_explicit_fallback(
    tmp_path, documents
):
    service, _, _, _, llm = _service(
        tmp_path, documents=documents, llm_response="Unsupported answer."
    )

    result = service.answer("¿Qué formas de pago aceptan?")

    assert result["answer"] == SPANISH_FALLBACK_RESPONSE
    assert result["sources"] == []
    assert llm.prompts == []


def test_answer_ignores_documents_outside_the_approved_directory(tmp_path):
    faq = _approved_document("Payments are debit and credit cards.")
    faq.metadata["source"] = str(tmp_path / "unapproved" / "draft.md")
    service, _, _, _, llm = _service(tmp_path, documents=[faq])

    result = service.answer("What payment methods are accepted?")

    assert result == {"answer": FALLBACK_RESPONSE, "sources": []}
    assert llm.prompts == []


def test_answering_never_reingests_conversation_or_dynamic_catalog_context(tmp_path):
    faq = _approved_document("Se puede pagar con tarjetas.")
    service, _, vector_store, _, _ = _service(tmp_path, documents=[faq])
    service.ingest_approved_sources()
    indexed_before_answer = list(vector_store.documents)
    calls_before_answer = vector_store.add_calls

    service.answer("¿Qué juegos tienen disponibles?")

    assert vector_store.add_calls == calls_before_answer
    assert vector_store.documents == indexed_before_answer
    indexed_content = "\n".join(
        document.page_content for document in vector_store.documents
    )
    assert CATALOG_MARKER not in indexed_content
    assert CONVERSATION_MARKER not in indexed_content


def test_ollama_provider_is_lazy_and_rejects_non_local_endpoints():
    provider = OllamaChatProvider()

    assert provider._client is None
    assert provider.model == "deepseek-r1:8b"
    with pytest.raises(ValueError, match="local HTTP endpoint"):
        OllamaChatProvider(base_url="https://example.test")


def test_ollama_provider_sanitizes_adapter_errors(monkeypatch):
    class BrokenChat:
        def __init__(self, **kwargs):
            pass

        def invoke(self, prompt):
            raise RuntimeError("private prompt and upstream URL")

    monkeypatch.setitem(
        sys.modules,
        "langchain_ollama",
        SimpleNamespace(ChatOllama=BrokenChat),
    )
    provider = OllamaChatProvider()

    with pytest.raises(LocalProviderError) as error:
        provider.invoke("private prompt")

    assert str(error.value) == "The local answer provider is unavailable."
    assert "private" not in str(error.value)
    assert "URL" not in str(error.value)


def test_answer_service_sanitizes_unexpected_upstream_errors():
    class BrokenRag:
        def answer(self, query):
            raise RuntimeError("secret prompt and internal traceback")

    service = GroundedAnswerService(BrokenRag())

    with pytest.raises(ChatbotServiceUnavailable) as error:
        service.answer("What payment methods are accepted?")

    assert str(error.value) == "The chatbot answer service is unavailable."
    assert "secret" not in str(error.value)
