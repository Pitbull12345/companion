import asyncio

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.agent.messages import Message, MessageRole
from companion.memory.manager import MemoryManager


class MemoryWithResult(MemoryManager):
    async def relevant_memories(self, query: str) -> tuple[str, ...]:
        assert query == "current question"
        return ("remembered preference",)


def test_context_ordering() -> None:
    conversation = ConversationManager()
    conversation.add_turn("previous question", "previous answer")
    builder = ContextBuilder("system prompt", conversation, MemoryWithResult())

    context = asyncio.run(builder.build("current question"))

    assert context == (
        Message(MessageRole.SYSTEM, "system prompt"),
        Message(MessageRole.SYSTEM, "remembered preference"),
        Message(MessageRole.USER, "previous question"),
        Message(MessageRole.ASSISTANT, "previous answer"),
        Message(MessageRole.USER, "current question"),
    )
