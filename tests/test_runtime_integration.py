import asyncio
from collections.abc import Sequence

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.agent.messages import Message, MessageRole
from companion.audio.interfaces import AudioFrame, AudioSegment, AudioSource
from companion.llm.router import LLMRouter
from companion.memory.manager import MemoryManager
from companion.runtime.assistant import AssistantRuntime, TurnResult
from companion.runtime.turn import TurnController, TurnState


class FakeAudioSource:
    def __init__(self, frames: tuple[AudioFrame, ...]) -> None:
        self.frames = list(frames)

    async def read_frame(self) -> AudioFrame:
        return self.frames.pop(0)


class FakeVAD:
    async def capture_utterance(self, source: AudioSource) -> AudioSegment:
        return AudioSegment((await source.read_frame(),))


class FakeSTT:
    def __init__(self, expected_audio: bytes) -> None:
        self.expected_audio = expected_audio

    async def transcribe(self, audio: AudioSegment) -> str:
        assert audio.frames[0].data == self.expected_audio
        return "What did I say?"


class FakeLLM:
    def __init__(self) -> None:
        self.messages: tuple[Message, ...] = ()

    async def generate(self, messages: Sequence[Message]) -> str:
        self.messages = tuple(messages)
        return "You asked a question."


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)


def test_complete_injected_speech_turn() -> None:
    audio_bytes = b"\x01\x00\x02\x00"
    source = FakeAudioSource((AudioFrame(audio_bytes),))
    conversation = ConversationManager()
    conversation.add_turn("Previous question", "Previous answer")
    llm = FakeLLM()
    tts = FakeTTS()
    turns = TurnController()
    runtime = AssistantRuntime(
        audio_source=source,
        vad=FakeVAD(),
        stt=FakeSTT(audio_bytes),
        context_builder=ContextBuilder(
            "You are Companion.", conversation, MemoryManager()
        ),
        llm=LLMRouter(llm),
        tts=tts,
        conversation=conversation,
        turn_controller=turns,
    )

    result = asyncio.run(runtime.run_turn())

    assert result == TurnResult("What did I say?", "You asked a question.")
    assert llm.messages == (
        Message(MessageRole.SYSTEM, "You are Companion."),
        Message(MessageRole.USER, "Previous question"),
        Message(MessageRole.ASSISTANT, "Previous answer"),
        Message(MessageRole.USER, "What did I say?"),
    )
    assert tts.spoken == ["You asked a question."]
    assert conversation.history[-2:] == (
        Message(MessageRole.USER, "What did I say?"),
        Message(MessageRole.ASSISTANT, "You asked a question."),
    )
    assert turns.state is TurnState.LISTENING
    assert source.frames == []
