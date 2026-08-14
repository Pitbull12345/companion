import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from companion.agent.messages import Message, MessageRole
from companion.application import (
    ApplicationConfig,
    CompositionFactories,
    TTSProviderRegistry,
    compose_character_runtime,
    create_default_llm_registry,
)
from companion.audio.interfaces import AudioClip, AudioFrame, AudioSegment
from companion.character import load_character
from companion.llm.errors import LLMError
from companion.llm.interfaces import LLMProvider
from companion.llm.openrouter import OpenRouterLLMProvider


class FakeResponse:
    def __init__(self, payload: Any = None, *, status: int = 200, json_error=None):
        self._payload = payload
        self.status_code = status
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://openrouter.test/api/v1/chat/completions")
            raise httpx.HTTPStatusError(
                "request failed",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeClient:
    def __init__(self, results: Sequence[Any]) -> None:
        self._results = iter(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.close_calls = 0

    async def post(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((path, kwargs))
        result = next(self._results)
        if isinstance(result, BaseException):
            raise result
        return result

    async def aclose(self) -> None:
        self.close_calls += 1


def user_message(text: str = "hello") -> tuple[Message, ...]:
    return (Message(MessageRole.USER, text),)


def test_request_maps_roles_model_auth_and_reuses_client() -> None:
    async def exercise() -> None:
        client = FakeClient(
            [
                FakeResponse({"choices": [{"message": {"content": " first "}}]}),
                FakeResponse({"choices": [{"message": {"content": "second"}}]}),
            ]
        )
        provider = OpenRouterLLMProvider("vendor/model", "test-key", client=client)
        messages = (
            Message(MessageRole.SYSTEM, "prompt"),
            Message(MessageRole.USER, "question"),
            Message(MessageRole.ASSISTANT, "prior answer"),
        )

        assert await provider.generate(messages) == "first"
        assert await provider.generate(user_message("next")) == "second"
        path, request = client.calls[0]
        assert path == "/api/v1/chat/completions"
        assert request["headers"] == {"Authorization": "Bearer test-key"}
        assert request["json"] == {
            "model": "vendor/model",
            "messages": [
                {"role": "system", "content": "prompt"},
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "prior answer"},
            ],
            "stream": False,
        }
        assert len(client.calls) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "missing assistant content"),
        ({"choices": []}, "missing assistant content"),
        ({"choices": [{}]}, "missing assistant content"),
        ({"choices": [{"message": {}}]}, "missing assistant content"),
        ({"choices": [{"message": {"content": None}}]}, "not text"),
        ({"choices": [{"message": {"content": " \n "}}]}, "empty assistant"),
    ],
)
def test_malformed_or_empty_response_is_rejected(payload: Any, message: str) -> None:
    async def exercise() -> None:
        provider = OpenRouterLLMProvider(
            "model", "key", client=FakeClient([FakeResponse(payload)])
        )
        with pytest.raises(LLMError, match=message):
            await provider.generate(user_message())

    asyncio.run(exercise())


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_http_status_is_translated_without_secret(status: int) -> None:
    async def exercise() -> None:
        provider = OpenRouterLLMProvider(
            "model", "never-print-this", client=FakeClient([FakeResponse(status=status)])
        )
        with pytest.raises(LLMError, match=f"HTTP {status}") as raised:
            await provider.generate(user_message())
        assert "never-print-this" not in str(raised.value)
        assert "never-print-this" not in repr(provider)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (httpx.ReadTimeout("slow"), "timed out"),
        (httpx.ConnectError("offline"), "request failed"),
    ],
)
def test_network_failures_are_translated(failure: Exception, message: str) -> None:
    async def exercise() -> None:
        provider = OpenRouterLLMProvider(
            "model", "key", client=FakeClient([failure])
        )
        with pytest.raises(LLMError, match=message) as raised:
            await provider.generate(user_message())
        assert raised.value.__cause__ is failure

    asyncio.run(exercise())


def test_malformed_json_is_translated() -> None:
    async def exercise() -> None:
        failure = ValueError("bad body")
        provider = OpenRouterLLMProvider(
            "model", "key", client=FakeClient([FakeResponse(json_error=failure)])
        )
        with pytest.raises(LLMError, match="malformed JSON"):
            await provider.generate(user_message())

    asyncio.run(exercise())


def test_cancellation_propagates() -> None:
    class BlockingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([])
            self.started = asyncio.Event()

        async def post(self, path: str, **kwargs: Any) -> FakeResponse:
            self.started.set()
            await asyncio.Event().wait()

    async def exercise() -> None:
        client = BlockingClient()
        provider = OpenRouterLLMProvider("model", "key", client=client)
        request = asyncio.create_task(provider.generate(user_message()))
        await client.started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

    asyncio.run(exercise())


def test_owned_client_is_lazy_reused_and_closed_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[FakeClient] = []
    options: list[dict[str, Any]] = []

    def create_client(**kwargs: Any) -> FakeClient:
        options.append(kwargs)
        client = FakeClient(
            [
                FakeResponse({"choices": [{"message": {"content": "one"}}]}),
                FakeResponse({"choices": [{"message": {"content": "two"}}]}),
            ]
        )
        clients.append(client)
        return client

    monkeypatch.setattr("companion.llm.openrouter.httpx.AsyncClient", create_client)
    provider = OpenRouterLLMProvider(
        "model", "secret", base_url="https://router.test", timeout=12.5
    )

    assert options == []

    async def exercise() -> None:
        assert await provider.generate(user_message()) == "one"
        assert await provider.generate(user_message()) == "two"
        await provider.close()
        await provider.close()

    asyncio.run(exercise())

    assert options == [{"base_url": "https://router.test", "timeout": 12.5}]
    assert len(clients[0].calls) == 2
    assert clients[0].close_calls == 1


def test_close_before_generate_does_not_create_owned_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creation_calls = 0

    def create_client(**kwargs: Any) -> FakeClient:
        nonlocal creation_calls
        creation_calls += 1
        return FakeClient([])

    monkeypatch.setattr("companion.llm.openrouter.httpx.AsyncClient", create_client)
    provider = OpenRouterLLMProvider("model", "secret")

    async def exercise() -> None:
        await provider.close()
        await provider.close()

    asyncio.run(exercise())
    assert creation_calls == 0


def test_injected_client_is_not_closed_and_contract_is_satisfied() -> None:
    class FalseyClient(FakeClient):
        def __bool__(self) -> bool:
            return False

    async def consume(provider: LLMProvider) -> str:
        return await provider.generate(user_message())

    async def exercise() -> None:
        client = FalseyClient(
            [FakeResponse({"choices": [{"message": {"content": "ok"}}]})]
        )
        provider = OpenRouterLLMProvider("model", "key", client=client)
        assert await consume(provider) == "ok"
        await provider.close()
        assert client.close_calls == 0

    asyncio.run(exercise())


def test_character_integration_reuses_openrouter_and_closes_owned_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = tmp_path / "character"
    package.mkdir()
    (package / "character.toml").write_text(
        """
id = "remote"
name = "Remote"
system_prompt = "Remote personality."

[llm]
provider = "openrouter"
model = "test/model"

[tts]
provider = "fake-tts"
voice = "voice"
"""
    )
    client = FakeClient(
        [
            FakeResponse({"choices": [{"message": {"content": "answer one"}}]}),
            FakeResponse({"choices": [{"message": {"content": "answer two"}}]}),
        ]
    )
    monkeypatch.setattr(
        "companion.llm.openrouter.httpx.AsyncClient", lambda **options: client
    )

    class Source:
        def __init__(self) -> None:
            self.close_calls = 0

        async def read_frame(self):
            raise AssertionError("fake VAD does not read the source")

        async def close(self) -> None:
            self.close_calls += 1

    class VAD:
        async def capture_utterance(self, source):
            return AudioSegment((AudioFrame(b"\0\0", 16_000, 1, 2),))

    class STT:
        def __init__(self) -> None:
            self.calls = 0

        async def transcribe(self, audio):
            self.calls += 1
            return f"question {self.calls}"

    class TTS:
        async def synthesize(self, text):
            return AudioClip(b"\0\0", 16_000, 1, 2)

    class Output:
        async def play(self, audio):
            return None

    source = Source()
    tts_registry: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()
    tts_registry.register("fake-tts", lambda preference, config: TTS())
    application = None
    turns = 0

    def completed(result) -> None:
        nonlocal turns
        turns += 1
        if turns == 2:
            application.loop.request_stop()

    application = compose_character_runtime(
        load_character(package),
        ApplicationConfig("whisper", openrouter_api_key="test-key"),
        llm_registry=create_default_llm_registry(),
        tts_registry=tts_registry,
        factories=CompositionFactories(
            audio_source=lambda: source,
            vad=VAD,
            stt=lambda path: STT(),
            audio_output=Output,
        ),
        on_turn_completed=completed,
    )
    asyncio.run(application.run())

    assert len(client.calls) == 2
    first_messages = client.calls[0][1]["json"]["messages"]
    second_messages = client.calls[1][1]["json"]["messages"]
    assert first_messages[0] == {"role": "system", "content": "Remote personality."}
    assert second_messages == [
        {"role": "system", "content": "Remote personality."},
        {"role": "user", "content": "question 1"},
        {"role": "assistant", "content": "answer one"},
        {"role": "user", "content": "question 2"},
    ]
    assert client.close_calls == 1
    assert source.close_calls == 1
