from companion.agent.conversation import ConversationManager
from companion.agent.messages import Message, MessageRole
from companion.memory.manager import MemoryManager


class ContextBuilder:
    def __init__(
        self,
        system_prompt: str,
        conversation: ConversationManager,
        memory: MemoryManager,
    ) -> None:
        self._system_prompt = system_prompt
        self._conversation = conversation
        self._memory = memory

    async def build(self, user_text: str) -> tuple[Message, ...]:
        memories = await self._memory.relevant_memories(user_text)
        memory_messages = tuple(
            Message(MessageRole.SYSTEM, memory) for memory in memories
        )
        return (
            Message(MessageRole.SYSTEM, self._system_prompt),
            *memory_messages,
            *self._conversation.history,
            Message(MessageRole.USER, user_text),
        )
