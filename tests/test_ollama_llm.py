import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from companion.agent.messages import Message, MessageRole
from companion.llm.errors import LLMError
from companion.llm.interfaces import LLMProvider
from companion.llm.ollama import OllamaLLMProvider


class FakeOllamaClient:
    def __init__(self, results: Sequence[Any]) -> None:
        self._results = iter(results)
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        stream: bool,
    ) -> Any:
        self.calls.append(
            {"model": model, "messages": list(messages), "stream": stream}
        )
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        return result


def test_default_client_creation_passes_configured_host_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, **options: Any) -> None:
            calls.append(options)

    monkeypatch.setattr("ollama.AsyncClient", FakeAsyncClient)

    OllamaLLMProvider(
        "model",
        host="http://ollama.internal:11434",
        timeout=12.5,
    )

    assert calls == [
        {"host": "http://ollama.internal:11434", "timeout": 12.5}
    ]


def test_message_mapping_order_model_and_successful_response() -> None:
    async def exercise() -> None:
        client = FakeOllamaClient(
            [{"message": {"role": "assistant", "content": "  hello\n world  "}}]
        )
        provider = OllamaLLMProvider("local-model", client=client)
        messages = (
            Message(MessageRole.SYSTEM, "system prompt"),
            Message(MessageRole.USER, "question"),
            Message(MessageRole.ASSISTANT, "earlier answer"),
        )

        assert await provider.generate(messages) == "hello world"
        assert client.calls == [
            {
                "model": "local-model",
                "messages": [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "question"},
                    {"role": "assistant", "content": "earlier answer"},
                ],
                "stream": False,
            }
        ]

    asyncio.run(exercise())


def test_empty_message_sequence_fails_without_request() -> None:
    async def exercise() -> None:
        client = FakeOllamaClient([])
        provider = OllamaLLMProvider("model", client=client)

        with pytest.raises(LLMError, match="empty message sequence"):
            await provider.generate(())
        assert client.calls == []

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({}, "missing assistant content"),
        ({"message": {}}, "missing assistant content"),
        ({"message": {"content": None}}, "not text"),
        ({"message": {"content": " \n "}}, "empty assistant content"),
    ],
)
def test_malformed_or_empty_response_fails_clearly(
    response: Any, message: str
) -> None:
    async def exercise() -> None:
        provider = OllamaLLMProvider(
            "model", client=FakeOllamaClient([response])
        )
        with pytest.raises(LLMError, match=message):
            await provider.generate((Message(MessageRole.USER, "hello"),))

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "failure",
    [ConnectionError("connection refused"), RuntimeError("model not found")],
)
def test_request_and_model_failures_are_wrapped(failure: Exception) -> None:
    async def exercise() -> None:
        provider = OllamaLLMProvider(
            "model", client=FakeOllamaClient([failure])
        )
        with pytest.raises(LLMError, match=str(failure)) as raised:
            await provider.generate((Message(MessageRole.USER, "hello"),))
        assert raised.value.__cause__ is failure

    asyncio.run(exercise())


def test_repeated_calls_and_reuse_after_failure() -> None:
    async def exercise() -> None:
        client = FakeOllamaClient(
            [RuntimeError("temporary failure"), {"message": {"content": "recovered"}},
             {"message": {"content": "again"}}]
        )
        provider = OllamaLLMProvider("model", client=client)
        message = (Message(MessageRole.USER, "hello"),)

        with pytest.raises(LLMError, match="temporary failure"):
            await provider.generate(message)
        assert await provider.generate(message) == "recovered"
        assert await provider.generate(message) == "again"
        assert len(client.calls) == 3

    asyncio.run(exercise())


def test_cancellation_propagates() -> None:
    class BlockingClient:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def chat(
            self,
            *,
            model: str,
            messages: Sequence[Mapping[str, str]],
            stream: bool,
        ) -> Any:
            self.started.set()
            await asyncio.Event().wait()

    async def exercise() -> None:
        client = BlockingClient()
        provider = OllamaLLMProvider("model", client=client)
        request = asyncio.create_task(
            provider.generate((Message(MessageRole.USER, "hello"),))
        )
        await client.started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

    asyncio.run(exercise())


def test_implementation_satisfies_existing_llm_contract() -> None:
    async def consume(llm: LLMProvider, messages: Sequence[Message]) -> str:
        return await llm.generate(messages)

    async def exercise() -> None:
        provider = OllamaLLMProvider(
            "model", client=FakeOllamaClient([{"message": {"content": "contract"}}])
        )
        assert await consume(
            provider, (Message(MessageRole.USER, "hello"),)
        ) == "contract"

    asyncio.run(exercise())
