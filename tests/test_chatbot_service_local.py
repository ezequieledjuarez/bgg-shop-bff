from pathlib import Path
from tempfile import TemporaryDirectory

import langchain_ollama

from src.chatbot import service as chatbot_service


class DeterministicEmbeddings:
    def __init__(self, **kwargs):
        pass

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class RecordingLlm:
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return "The approved synthetic FAQ supports this answer."


def test_local_chroma_retrieves_and_synchronizes_approved_faq(monkeypatch):
    llm = RecordingLlm()
    monkeypatch.setenv("CHAT_EMBEDDING_MODEL", "deterministic-test")
    monkeypatch.setattr(
        langchain_ollama, "OllamaEmbeddings", DeterministicEmbeddings
    )
    monkeypatch.setattr(
        chatbot_service, "OllamaChatProvider", lambda base_url: llm
    )

    query = "Where is the synthetic parcel pickup rule?"
    with TemporaryDirectory(
        prefix=".chatbot-chroma-", dir=Path(__file__).parents[1]
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        approved_directory = temporary_path / "approved"
        approved_directory.mkdir()
        source = approved_directory / "synthetic-faq.md"
        source.write_text(
            "---\ntitle: Synthetic Parcel FAQ\napproved: true\nstatus: active\n---\n"
            "# Synthetic Parcel FAQ\n\n"
            "The synthetic parcel pickup rule is collect parcels at counter Alpha.",
            encoding="utf-8",
        )

        service = chatbot_service.create_local_chatbot_service(
            approved_sources_dir=approved_directory,
            persist_directory=temporary_path / "chroma",
        )

        initial_documents = service.rag.retriever.invoke(query)
        assert len(initial_documents) == 1
        assert "counter Alpha" in initial_documents[0].page_content
        assert service.answer(query)["answer"] == (
            "The approved synthetic FAQ supports this answer."
        )
        assert "counter Alpha" in llm.prompts[-1]

        source.write_text(
            "---\ntitle: Synthetic Parcel FAQ\napproved: true\nstatus: active\n---\n"
            "# Synthetic Parcel FAQ\n\n"
            "The synthetic parcel pickup rule is collect parcels at counter Beta.",
            encoding="utf-8",
        )
        service.ingest_approved_sources()
        updated_documents = service.rag.retriever.invoke(query)
        assert len(updated_documents) == 1
        assert "counter Beta" in updated_documents[0].page_content
        assert "counter Alpha" not in updated_documents[0].page_content
        service.answer(query)
        assert "counter Beta" in llm.prompts[-1]
        assert "counter Alpha" not in llm.prompts[-1]

        source.write_text(
            "---\ntitle: Synthetic Parcel FAQ\napproved: false\nstatus: withdrawn\n---\n"
            "# Synthetic Parcel FAQ\n\n"
            "The synthetic parcel pickup rule is withdrawn.",
            encoding="utf-8",
        )
        service.ingest_approved_sources()
        assert service.rag.retriever.invoke(query) == []
        assert service.answer(query)["sources"] == []
