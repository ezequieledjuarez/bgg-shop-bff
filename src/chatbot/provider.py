import ipaddress
import os
from urllib.parse import urlsplit

import requests


MODEL_NAME = "deepseek-r1:8b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_TIMEOUT_SECONDS = 30


class LocalProviderError(RuntimeError):
    pass


def local_ollama_base_url(value=None):
    value = value or os.getenv("CHAT_OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").casefold()
    is_loopback = hostname == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if (
        not is_loopback
        or parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Ollama must use a local HTTP endpoint")
    return value.rstrip("/")


class OllamaChatProvider:
    def __init__(self, base_url=None):
        self.model = MODEL_NAME
        self.base_url = local_ollama_base_url(base_url)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from langchain_ollama import ChatOllama

            self._client = ChatOllama(
                model=self.model,
                base_url=self.base_url,
            )
        return self._client

    def invoke(self, prompt):
        try:
            response = self._get_client().invoke(prompt)
            content = getattr(response, "content", response)
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty provider response")
            return content.strip()
        except Exception:
            raise LocalProviderError(
                "The local answer provider is unavailable."
            ) from None


class OpenRouterWithLocalFallbackProvider:
    def __init__(self, local_provider=None):
        self.local_provider = local_provider or OllamaChatProvider()

    @staticmethod
    def _openrouter_configuration():
        api_key = os.getenv("OPENROUTER_API_KEY")
        model = os.getenv("OPENROUTER_MODEL")
        url = os.getenv("OPENROUTER_API_URL", OPENROUTER_URL)
        if (
            url != OPENROUTER_URL
            or not isinstance(api_key, str)
            or not api_key.strip()
            or any(character.isspace() for character in api_key.strip())
            or not isinstance(model, str)
            or not model.strip()
            or any(character.isspace() for character in model.strip())
        ):
            return None
        return api_key.strip(), model.strip(), url

    @staticmethod
    def _openrouter_answer(prompt, api_key, model, url):
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=OPENROUTER_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty provider response")
        return content.strip()

    def invoke(self, prompt):
        configuration = self._openrouter_configuration()
        if configuration:
            try:
                return self._openrouter_answer(prompt, *configuration)
            except Exception:
                pass

        try:
            return self.local_provider.invoke(prompt)
        except Exception:
            raise LocalProviderError(
                "The answer providers are unavailable."
            ) from None
