import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .guardrails import message_language

FALLBACK_RESPONSE = (
    "I can’t answer with confidence because approved store information "
    "doesn’t support an answer. Please contact store support."
)
SPANISH_FALLBACK_RESPONSE = (
    "No puedo responder con confianza porque la información aprobada de la tienda "
    "no respalda una respuesta. Contacta al soporte de la tienda."
)

_FRONTMATTER = re.compile(
    r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL
)
_TITLE = re.compile(r"^\s*#\s+(.+?)\s*#*\s*$", re.MULTILINE)
_STORE_URL = re.compile(r"(?im)^Store URL:\s*http://localhost:\d+\s*$")
_WORDS = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = {
    "a",
    "about",
    "accept",
    "acceptan",
    "an",
    "and",
    "are",
    "can",
    "como",
    "con",
    "de",
    "del",
    "do",
    "el",
    "en",
    "es",
    "for",
    "from",
    "how",
    "i",
    "la",
    "las",
    "los",
    "me",
    "of",
    "our",
    "para",
    "por",
    "que",
    "se",
    "the",
    "to",
    "utilizar",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "you",
    "your",
}
_TOPICS = {
    "payment": re.compile(
        r"\b(pag[oa]s?|pagar|tarjetas?|debit|credit|transfer|payment|"
        r"mercado\s+pago)\b",
        re.IGNORECASE,
    ),
    "shipping": re.compile(
        r"\b(env[ií]os?|despach|correo argentino|shipping|delivery|entrega)\b",
        re.IGNORECASE,
    ),
    "returns": re.compile(
        r"\b(cancel|devoluci[oó]n|reembolso|refund|return|da[nñ]ad|no llega)\b",
        re.IGNORECASE,
    ),
    "stock": re.compile(
        r"\b(stock|disponible|disponibilidad|available|inventory)\b",
        re.IGNORECASE,
    ),
    "contact": re.compile(
        r"\b(contact|contactar|escrib|asistencia|support|ayuda)\b",
        re.IGNORECASE,
    ),
}
_PAYMENT_VALUES = {
    "debit": re.compile(r"\b(debit|d[eé]bito)\b", re.IGNORECASE),
    "credit": re.compile(r"\b(credit|cr[eé]dito)\b", re.IGNORECASE),
    "transfer": re.compile(r"\b(transfer|transferencia)\b", re.IGNORECASE),
    "cash": re.compile(r"\b(cash|efectivo)\b", re.IGNORECASE),
}
_EXCLUSIVE = re.compile(
    r"\b(only|exclusively|solo|solamente|únicamente|unicamente)\b",
    re.IGNORECASE,
)


@dataclass
class _Document:
    page_content: str
    metadata: dict


def _document(page_content, metadata):
    try:
        from langchain_core.documents import Document
    except ImportError:
        return _Document(page_content=page_content, metadata=metadata)
    return Document(page_content=page_content, metadata=metadata)


def _topic_set(text):
    return {name for name, pattern in _TOPICS.items() if pattern.search(text)}


def _has_relevant_evidence(query, documents):
    query_topics = _topic_set(query)
    if query_topics:
        return any(
            query_topics.intersection(
                _topic_set(
                    document.page_content
                    + " "
                    + str(document.metadata.get("title", ""))
                )
            )
            for document in documents
        )

    query_terms = {
        word.casefold()
        for word in _WORDS.findall(query)
        if word.casefold() not in _STOP_WORDS and len(word) > 2
    }
    return any(
        query_terms.intersection(
            {
                word.casefold()
                for word in _WORDS.findall(
                    document.page_content
                    + " "
                    + str(document.metadata.get("title", ""))
                )
                if word.casefold() not in _STOP_WORDS and len(word) > 2
            }
        )
        for document in documents
    )


def _conflicting_evidence(documents):
    for index, first in enumerate(documents):
        first_text = first.page_content
        for second in documents[index + 1 :]:
            if not _topic_set(first_text).intersection(
                _topic_set(second.page_content)
            ):
                continue
            first_values = {
                name
                for name, pattern in _PAYMENT_VALUES.items()
                if pattern.search(first_text)
            }
            second_values = {
                name
                for name, pattern in _PAYMENT_VALUES.items()
                if pattern.search(second.page_content)
            }
            if first_values and second_values and first_values != second_values:
                if _EXCLUSIVE.search(first_text) or _EXCLUSIVE.search(
                    second.page_content
                ):
                    return True
    return False


def _metadata_status(metadata):
    approved = metadata.get("approved", True)
    status = str(metadata.get("status", "active")).casefold()
    return approved is True and status in {"active", "approved"}


def _source_is_in_root(source, root):
    if not source:
        return False
    try:
        source_path = Path(os.path.abspath(os.path.normpath(os.fspath(source))))
        relative = source_path.relative_to(root)
        candidate = root
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                return False
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _safe_source_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return value


class ApprovedFaqRag:
    def __init__(
        self,
        approved_sources_dir,
        embeddings,
        vector_store,
        retriever,
        llm,
    ):
        self.approved_sources_dir = Path(approved_sources_dir)
        self.embeddings = embeddings
        self.vector_store = vector_store
        self.retriever = retriever
        self.llm = llm

    def _approved_documents(self, root):
        documents = {}
        if not root.is_dir():
            return documents

        for source_path in sorted(root.rglob("*")):
            if source_path.suffix.casefold() not in {".md", ".txt"}:
                continue
            try:
                if source_path.is_symlink():
                    continue
                resolved_source = source_path.resolve(strict=True)
                if (
                    not resolved_source.is_relative_to(root)
                    or not source_path.is_file()
                ):
                    continue
                raw_content = source_path.read_text(encoding="utf-8")
            except (OSError, RuntimeError, UnicodeError):
                continue

            source_metadata = {}
            match = _FRONTMATTER.match(raw_content)
            if match:
                try:
                    source_metadata = yaml.safe_load(match.group(1)) or {}
                except yaml.YAMLError:
                    continue
                if not isinstance(source_metadata, dict):
                    continue
                raw_content = raw_content[match.end() :]

            if not _metadata_status(source_metadata):
                continue

            content = _STORE_URL.sub("Store URL: http://localhost:3030", raw_content)
            title_match = _TITLE.search(content)
            title = source_metadata.get("title") or (
                title_match.group(1).strip()
                if title_match
                else source_path.stem
            )
            metadata = {
                "title": str(title),
                "source": str(resolved_source),
                "approved": True,
                "status": "active",
            }
            embedded_url = re.search(
                r"(?im)^Store URL:\s*(https?://\S+)\s*$", content
            )
            source_url = _safe_source_url(
                source_metadata.get("url")
                or (embedded_url.group(1) if embedded_url else None)
            )
            if source_url:
                metadata["url"] = source_url
            document_id = hashlib.sha256(
                f"{resolved_source}:0".encode("utf-8")
            ).hexdigest()
            documents[document_id] = _document(content, metadata)

        return documents

    def _synchronize_index(self, root, desired_documents):
        existing = self.vector_store.get(include=["documents", "metadatas"])
        existing_ids = existing.get("ids", [])
        existing_contents = existing.get("documents", [])
        existing_metadata = existing.get("metadatas", [])
        desired_ids = set(desired_documents)
        stale_ids = []
        unchanged_ids = set()
        indexed_ids = set(existing_ids)

        for index, document_id in enumerate(existing_ids):
            metadata = (
                existing_metadata[index]
                if index < len(existing_metadata) and existing_metadata[index]
                else {}
            )
            if not _source_is_in_root(metadata.get("source"), root):
                stale_ids.append(document_id)
                continue
            if document_id not in desired_ids:
                stale_ids.append(document_id)
                continue
            if (
                index < len(existing_contents)
                and existing_contents[index] == desired_documents[document_id].page_content
                and metadata == desired_documents[document_id].metadata
            ):
                unchanged_ids.add(document_id)

        if stale_ids:
            self.vector_store.delete(ids=stale_ids)

        changed_ids = [
            document_id
            for document_id in desired_documents
            if document_id not in unchanged_ids
        ]
        updated_ids = [
            document_id for document_id in changed_ids if document_id in indexed_ids
        ]
        if updated_ids:
            self.vector_store.update_documents(
                ids=updated_ids,
                documents=[
                    desired_documents[document_id] for document_id in updated_ids
                ],
            )
        added_ids = [
            document_id for document_id in changed_ids if document_id not in indexed_ids
        ]
        if added_ids:
            self.vector_store.add_documents(
                [desired_documents[document_id] for document_id in added_ids],
                ids=added_ids,
            )
        return len(desired_documents)

    def ingest_approved_sources(self):
        root = self.approved_sources_dir.resolve()
        desired_documents = self._approved_documents(root)
        return self._synchronize_index(root, desired_documents)

    def answer(self, query):
        if not isinstance(query, str) or not query.strip():
            return {"answer": FALLBACK_RESPONSE, "sources": []}
        language = message_language(query)
        fallback = SPANISH_FALLBACK_RESPONSE if language == "es" else FALLBACK_RESPONSE

        if re.search(
            r"\b(juegos?|games?|recommendations?)\b", query, re.IGNORECASE
        ):
            return {"answer": fallback, "sources": []}

        retrieved = self.retriever.invoke(query)
        if not isinstance(retrieved, (list, tuple)):
            retrieved = []
        root = self.approved_sources_dir.resolve()
        approved = []
        for document in retrieved:
            metadata = getattr(document, "metadata", None)
            content = getattr(document, "page_content", None)
            if (
                not isinstance(metadata, dict)
                or not _metadata_status(metadata)
                or not isinstance(content, str)
                or not content.strip()
                or not _source_is_in_root(metadata.get("source"), root)
            ):
                continue
            if _has_relevant_evidence(query, [document]):
                approved.append(document)

        if (
            not approved
            or _conflicting_evidence(approved)
        ):
            return {"answer": fallback, "sources": []}

        excerpts = "\n\n".join(
            f"Approved source: {document.metadata.get('title', 'Store FAQ')}\n"
            f"Excerpt:\n{document.page_content}"
            for document in approved
        )
        prompt = (
            f"Answer in {'Spanish' if language == 'es' else 'English'}, matching "
            "the language of the question regardless of the excerpts' language. "
            "Answer the buyer's store FAQ question using only the approved "
            "excerpts below. Do not use prior knowledge, invent facts, or "
            "include information not supported by an excerpt. If the excerpts "
            "do not directly support an answer, reply exactly with: "
            f"{fallback}\n\n"
            f"Approved excerpts:\n{excerpts}\n\nQuestion: {query}"
        )
        answer = self.llm.invoke(prompt)
        answer = getattr(answer, "content", answer)
        if not isinstance(answer, str) or not answer.strip():
            return {"answer": fallback, "sources": []}

        sources = []
        seen_sources = set()
        for document in approved:
            metadata = document.metadata
            title = str(metadata.get("title", "Store FAQ"))
            url = _safe_source_url(metadata.get("url"))
            source = {"title": title}
            if url:
                source["url"] = url
            key = (title, url)
            if key not in seen_sources:
                sources.append(source)
                seen_sources.add(key)
        return {"answer": answer.strip(), "sources": sources}
