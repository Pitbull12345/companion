import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import httpx

from companion.agent.messages import Message
from companion.llm.errors import LLMError


class OpenRouterResponse(Protocol):
    status_code: int

    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class OpenRouterClient(Protocol):
    async def post(self, path: str, **kwargs: Any) -> OpenRouterResponse: ...

    async def aclose(self) -> None: ...


class OpenRouterLLMProvider:
    """Non-streaming OpenRouter chat-completions adapter."""

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        base_url: str = "https://openrouter.ai",
        timeout: float = 30.0,
        client: OpenRouterClient | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._closed = False
        self._client_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()

    async def _get_client(self) -> OpenRouterClient:
        async with self._client_lock:
            if self._closed:
                raise LLMError("OpenRouter provider is closed")
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self._base_url, timeout=self._timeout
                )
            return self._client

    @staticmethod
    def _assistant_content(payload: Any) -> str:
        try:
            choices = payload["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError
            message = choices[0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("malformed OpenRouter response: missing assistant content") from exc
        if not isinstance(content, str):
            raise LLMError("malformed OpenRouter response: assistant content is not text")
        normalized = " ".join(content.split())
        if not normalized:
            raise LLMError("OpenRouter returned empty assistant content")
        return normalized

    async def generate(self, messages: Sequence[Message]) -> str:
        if not messages:
            raise LLMError("cannot generate from an empty message sequence")
        body = {
            "model": self._model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in messages
            ],
            "stream": False,
        }
        try:
            client = await self._get_client()
            response = await client.post(
                "/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMError("OpenRouter request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"OpenRouter request failed with HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMError("OpenRouter request failed") from exc
        except ValueError as exc:
            raise LLMError("OpenRouter returned malformed JSON") from exc
        return self._assistant_content(payload)

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self._owns_client and self._client is not None:
                await self._client.aclose()
