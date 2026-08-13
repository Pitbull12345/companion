from collections.abc import Sequence
from typing import Protocol

from companion.agent.messages import Message


class LLMProvider(Protocol):
    async def generate(self, messages: Sequence[Message]) -> str: ...
