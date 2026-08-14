import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from companion.agent.messages import Message
from companion.llm.errors import LLMError


class OllamaClient(Protocol):
    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        stream: bool,
    ) -> Any: ...


def _create_client(host: str, timeout: float | None) -> OllamaClient:
    try:
        from ollama import AsyncClient

        options: dict[str, Any] = {"host": host}
        if timeout is not None:
            options["timeout"] = timeout
        return AsyncClient(**options)
    except Exception as exc:
        raise LLMError(f"could not initialize Ollama client: {exc}") from exc


class OllamaLLMProvider:
    """Async Ollama adapter using a reusable client.

    Concurrent calls are supported and delegated directly to the owned async
    client. The provider does not serialize requests or create background jobs.
    """

    def __init__(
        self,
        model: str,
        *,
        host: str = "http://localhost:11434",
        timeout: float | None = None,
        client: OllamaClient | None = None,
    ) -> None:
        self._model = model
        self._client = client if client is not None else _create_client(host, timeout)

    @staticmethod
    def _response_content(response: Any) -> str:
        try:
            message = (
                response["message"]
                if isinstance(response, Mapping)
                else response.message
            )
            content = (
                message["content"] if isinstance(message, Mapping) else message.content
            )
        except (AttributeError, KeyError, TypeError) as exc:
            raise LLMError("malformed Ollama response: missing assistant content") from exc

        if not isinstance(content, str):
            raise LLMError("malformed Ollama response: assistant content is not text")
        normalized = " ".join(content.split())
        if not normalized:
            raise LLMError("Ollama returned empty assistant content")
        return normalized

    async def generate(self, messages: Sequence[Message]) -> str:
        if not messages:
            raise LLMError("cannot generate from an empty message sequence")

        ollama_messages = [
            {"role": message.role.value, "content": message.content}
            for message in messages
        ]
        try:
            response = await self._client.chat(
                model=self._model,
                messages=ollama_messages,
                stream=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        return self._response_content(response)
