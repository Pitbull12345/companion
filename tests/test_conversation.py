from companion.agent.conversation import ConversationManager
from companion.agent.messages import Message, MessageRole


def test_stores_completed_turns() -> None:
    conversation = ConversationManager()

    conversation.add_turn("Hello", "Hi there")

    assert conversation.history == (
        Message(MessageRole.USER, "Hello"),
        Message(MessageRole.ASSISTANT, "Hi there"),
    )


def test_history_limit_counts_completed_turns() -> None:
    conversation = ConversationManager(history_limit=1)
    conversation.add_turn("first", "old response")

    conversation.add_turn("second", "new response")

    assert conversation.history == (
        Message(MessageRole.USER, "second"),
        Message(MessageRole.ASSISTANT, "new response"),
    )


def test_history_is_a_safe_snapshot() -> None:
    conversation = ConversationManager()
    conversation.add_turn("Hello", "Hi")
    snapshot = conversation.history

    snapshot += (Message(MessageRole.USER, "external"),)

    assert len(snapshot) == 3
    assert len(conversation.history) == 2


def test_clear_removes_history() -> None:
    conversation = ConversationManager()
    conversation.add_turn("Hello", "Hi")

    conversation.clear()

    assert conversation.history == ()
