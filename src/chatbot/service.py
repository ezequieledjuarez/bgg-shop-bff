import os
from pathlib import Path

from src.chatbot.provider import OllamaChatProvider, local_ollama_base_url
from src.chatbot.rag import ApprovedFaqRag


class ChatbotServiceUnavailable(RuntimeError):
    pass


class GroundedAnswerService:
    def __init__(self, rag):
        self.rag = rag

    def ingest_approved_sources(self):
        try:
            return self.rag.ingest_approved_sources()
        except Exception:
            raise ChatbotServiceUnavailable(
                "Approved store information is unavailable."
            ) from None

    def answer(self, query):
        try:
            return self.rag.answer(query)
        except Exception:
            raise ChatbotServiceUnavailable(
                "The chatbot answer service is unavailable."
            ) from None


def create_local_chatbot_service(
    approved_sources_dir,
    persist_directory=None,
):
    """Build the local stack; CHAT_EMBEDDING_MODEL must name a pulled Ollama embedder."""
    base_url = local_ollama_base_url()
    embedding_model = os.getenv("CHAT_EMBEDDING_MODEL")
    if not embedding_model:
        raise ValueError("Set CHAT_EMBEDDING_MODEL to a local Ollama embedding model.")
    from langchain_chroma import Chroma
    from langchain_ollama import OllamaEmbeddings
    persist_directory = persist_directory or os.getenv(
        "CHAT_CHROMA_DIR",
        str(Path(__file__).resolve().parents[2] / ".local" / "approved-faq-chroma"),
    )
    embeddings = OllamaEmbeddings(model=embedding_model, base_url=base_url)
    vector_store = Chroma(
        collection_name="approved_store_faq",
        persist_directory=str(persist_directory),
        embedding_function=embeddings,
    )
    retriever = vector_store.as_retriever(
        search_kwargs={
            "k": 4,
            "filter": {
                "$and": [
                    {"approved": True},
                    {"status": "active"},
                ]
            },
        }
    )
    rag = ApprovedFaqRag(
        approved_sources_dir=approved_sources_dir,
        embeddings=embeddings,
        vector_store=vector_store,
        retriever=retriever,
        llm=OllamaChatProvider(base_url=base_url),
    )
    service = GroundedAnswerService(rag)
    service.ingest_approved_sources()
    return service
