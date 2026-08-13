from collections.abc import Sequence

from companion.agent.messages import Message
from companion.llm.interfaces import LLMProvider


class LLMRouter:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def generate(self, messages: Sequence[Message]) -> str:
        return await self._provider.generate(messages)
