from collections import deque

from companion.agent.messages import Message, MessageRole


class ConversationManager:
    """Owns the completed turns in the current conversation."""

    def __init__(self, history_limit: int = 20) -> None:
        if history_limit < 0:
            raise ValueError("history_limit must be non-negative")
        self._turns: deque[tuple[Message, Message]] = deque(maxlen=history_limit)

    @property
    def history(self) -> tuple[Message, ...]:
        return tuple(message for turn in self._turns for message in turn)

    def add_turn(self, user_text: str, assistant_text: str) -> None:
        self._turns.append(
            (
                Message(MessageRole.USER, user_text),
                Message(MessageRole.ASSISTANT, assistant_text),
            )
        )

    def clear(self) -> None:
        self._turns.clear()
