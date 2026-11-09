import requests
import pytest

from src.chatbot.provider import (
    OpenRouterWithLocalFallbackProvider,
)
from src.chatbot.service import ChatbotServiceUnavailable, GroundedAnswerService


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class FakeLocalProvider:
    def __init__(self, result="Local fallback answer.", error=None):
        self.result = result
        self.error = error
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        if self.error:
            raise self.error
        return self.payload


def _configured_provider(monkeypatch, local_provider=None):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "synthetic/provider-model")
    monkeypatch.delenv("OPENROUTER_API_URL", raising=False)
    return OpenRouterWithLocalFallbackProvider(
        local_provider=local_provider or FakeLocalProvider()
    )


@pytest.mark.parametrize("configured_url", [None, OPENROUTER_URL])
def test_openrouter_success_uses_expected_chat_completion_request(
    monkeypatch, configured_url
):
    local_provider = FakeLocalProvider()
    provider = _configured_provider(monkeypatch, local_provider)
    if configured_url is not None:
        monkeypatch.setenv("OPENROUTER_API_URL", configured_url)
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            {"choices": [{"message": {"content": "  Grounded answer.  "}}]}
        )

    monkeypatch.setattr("src.chatbot.provider.requests.post", fake_post)

    assert provider.invoke("Synthetic grounded prompt") == "Grounded answer."
    assert local_provider.prompts == []
    assert calls[0][1]["headers"]["Authorization"] == "Bearer " + "synthetic-test-key"
    assert calls == [
        (
            OPENROUTER_URL,
            {
                "headers": {
                    "Authorization": "Bearer synthetic-test-key",
                    "Content-Type": "application/json",
                },
                "json": {
                    "model": "synthetic/provider-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Synthetic grounded prompt",
                        }
                    ],
                },
                "timeout": 30,
            },
        )
    ]


@pytest.mark.parametrize(
    "configured_url",
    [
        "",
        "http://openrouter.ai/api/v1/chat/completions",
        "https://example.com/api/v1/chat/completions",
        "https://openrouter.ai.example.com/api/v1/chat/completions",
        "https://user@openrouter.ai/api/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions?key=synthetic",
        "https://openrouter.ai/api/v1/chat/completions#fragment",
        "https://openrouter.ai:443/api/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions/",
    ],
)
def test_invalid_openrouter_url_uses_local_without_remote_call(
    monkeypatch, configured_url
):
    local_provider = FakeLocalProvider()
    provider = _configured_provider(monkeypatch, local_provider)
    monkeypatch.setenv("OPENROUTER_API_URL", configured_url)
    remote_calls = []
    monkeypatch.setattr(
        "src.chatbot.provider.requests.post",
        lambda *args, **kwargs: remote_calls.append((args, kwargs)),
    )

    assert provider.invoke("Synthetic prompt") == "Local fallback answer."
    assert local_provider.prompts == ["Synthetic prompt"]
    assert remote_calls == []


def test_invalid_url_and_local_failure_are_sanitized(monkeypatch):
    local_provider = FakeLocalProvider(error=RuntimeError("synthetic secret"))
    provider = _configured_provider(monkeypatch, local_provider)
    monkeypatch.setenv("OPENROUTER_API_URL", "https://example.com/synthetic-secret")
    remote_calls = []
    monkeypatch.setattr(
        "src.chatbot.provider.requests.post",
        lambda *args, **kwargs: remote_calls.append((args, kwargs)),
    )

    class ProviderRag:
        def answer(self, query):
            return provider.invoke(query)

    with pytest.raises(ChatbotServiceUnavailable) as error:
        GroundedAnswerService(ProviderRag()).answer("Synthetic private prompt")

    assert str(error.value) == "The chatbot answer service is unavailable."
    assert local_provider.prompts == ["Synthetic private prompt"]
    assert remote_calls == []


@pytest.mark.parametrize(
    ("api_key", "model"),
    [
        (None, "synthetic/provider-model"),
        ("synthetic-test-key", None),
        ("   ", "synthetic/provider-model"),
        ("synthetic-test-key", " "),
    ],
)
def test_unconfigured_openrouter_falls_back_to_local(
    monkeypatch, api_key, model
):
    if api_key is None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENROUTER_API_KEY", api_key)
    if model is None:
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    else:
        monkeypatch.setenv("OPENROUTER_MODEL", model)
    local_provider = FakeLocalProvider()
    provider = OpenRouterWithLocalFallbackProvider(
        local_provider=local_provider
    )
    remote_calls = []
    monkeypatch.setattr(
        "src.chatbot.provider.requests.post",
        lambda *args, **kwargs: remote_calls.append((args, kwargs)),
    )

    assert provider.invoke("Synthetic prompt") == "Local fallback answer."
    assert local_provider.prompts == ["Synthetic prompt"]
    assert remote_calls == []


@pytest.mark.parametrize(
    "response",
    [
        requests.ConnectionError("synthetic transport detail"),
        FakeResponse(error=requests.HTTPError("synthetic upstream body")),
        FakeResponse(error=ValueError("synthetic malformed JSON")),
        FakeResponse({"choices": []}),
        FakeResponse({"choices": [{"message": {"content": "  "}}]}),
        FakeResponse({"choices": [{"message": {"content": None}}]}),
    ],
)
def test_openrouter_request_or_response_failure_falls_back_to_local(
    monkeypatch, response
):
    local_provider = FakeLocalProvider()
    provider = _configured_provider(monkeypatch, local_provider)

    def fake_post(*args, **kwargs):
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("src.chatbot.provider.requests.post", fake_post)

    assert provider.invoke("Synthetic prompt") == "Local fallback answer."
    assert local_provider.prompts == ["Synthetic prompt"]


def test_both_providers_failing_surface_only_safe_service_error(monkeypatch):
    local_provider = FakeLocalProvider(
        error=RuntimeError("synthetic local secret and traceback")
    )
    provider = _configured_provider(monkeypatch, local_provider)
    monkeypatch.setattr(
        "src.chatbot.provider.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.ConnectionError(
                "synthetic credential, prompt, and upstream URL"
            )
        ),
    )

    class ProviderRag:
        def answer(self, query):
            return provider.invoke(query)

    service = GroundedAnswerService(ProviderRag())

    with pytest.raises(ChatbotServiceUnavailable) as error:
        service.answer("Synthetic private prompt")

    assert str(error.value) == "The chatbot answer service is unavailable."
    assert "synthetic" not in str(error.value)
    assert "credential" not in str(error.value)
    assert "Synthetic private prompt" not in str(error.value)
