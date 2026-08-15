import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.application import (
    ApplicationConfig,
    ApplicationError,
    ApplicationStopped,
    CharacterLoaded,
    CompositionFactories,
    EventPublisher,
    LLMProviderRegistry,
    ResponseReady,
    SpeechFinished,
    SpeechStarted,
    StateChanged,
    TTSProviderRegistry,
    TranscriptReady,
    compose_character_runtime,
)
from companion.audio.interfaces import AudioClip, AudioFrame, AudioSegment
from companion.character import (
    AnimationDefinition,
    CharacterDefinition,
    LLMPreference,
    TTSPreference,
)
from companion.llm.router import LLMRouter
from companion.memory.manager import MemoryManager
from companion.runtime.assistant import AssistantRuntime
from companion.runtime.turn import TurnController, TurnState


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


class FakeSource:
    async def read_frame(self):
        raise AssertionError("VAD does not read the source")

    async def close(self) -> None:
        pass


class FakeVAD:
    async def capture_utterance(self, source):
        return AudioSegment((AudioFrame(b"\0\0", 16_000, 1, 2),))


class FakeSTT:
    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, audio):
        self.calls += 1
        return f"question {self.calls}"


class FakeLLM:
    def __init__(self, provider: str = "ollama") -> None:
        self.provider = provider
        self.calls = 0

    async def generate(self, messages):
        self.calls += 1
        return f"answer {self.calls}"


class FakeTTS:
    def __init__(self, provider: str = "piper") -> None:
        self.provider = provider

    async def synthesize(self, text):
        return AudioClip(b"\0\0", 16_000, 1, 2)


class FakeOutput:
    async def play(self, audio):
        pass


def make_runtime(observer, *, stt=None, llm=None, tts=None, output=None):
    conversation = ConversationManager()
    publisher = EventPublisher((observer,))
    controller = TurnController(
        on_transition=lambda state: publisher.publish(StateChanged(state))
    )
    return AssistantRuntime(
        audio_source=FakeSource(),
        vad=FakeVAD(),
        stt=stt or FakeSTT(),
        context_builder=ContextBuilder("Prompt", conversation, MemoryManager()),
        llm=LLMRouter(llm or FakeLLM()),
        tts=tts or FakeTTS(),
        audio_output=output or FakeOutput(),
        conversation=conversation,
        turn_controller=controller,
        event_observer=publisher,
    )


def turn_event_signature(events):
    return [
        (type(event), getattr(event, "state", None))
        for event in events
    ]


def test_event_values_are_immutable_and_safe() -> None:
    event = CharacterLoaded(
        "amy",
        "Amy",
        (("idle", "/characters/amy/idle.png"),),
        (("idle", (("/characters/amy/idle-0.png"),), 6.0, True),),
    )
    assert event.visuals == (("idle", "/characters/amy/idle.png"),)
    assert event.animations[0][0] == "idle"
    with pytest.raises(FrozenInstanceError):
        event.character_name = "changed"  # type: ignore[misc]

    secret = "Bearer extremely-secret-token"
    error = ApplicationError("response generation", "response generation failed")
    assert secret not in repr(error)
    assert all(
        not hasattr(candidate, "provider")
        for candidate in (
            event,
            StateChanged(TurnState.LISTENING),
            TranscriptReady("hello"),
            ResponseReady("hi"),
            SpeechStarted(),
            SpeechFinished(),
            error,
            ApplicationStopped(),
        )
    )


@pytest.mark.parametrize("llm_name", ["ollama", "openrouter"])
@pytest.mark.parametrize("tts_name", ["piper", "elevenlabs"])
def test_complete_turn_order_is_provider_neutral(llm_name: str, tts_name: str) -> None:
    observer = RecordingObserver()
    runtime = make_runtime(
        observer, llm=FakeLLM(llm_name), tts=FakeTTS(tts_name)
    )

    asyncio.run(runtime.run_turn())

    assert observer.events == [
        StateChanged(TurnState.TRANSCRIBING),
        TranscriptReady("question 1"),
        StateChanged(TurnState.THINKING),
        ResponseReady("answer 1"),
        StateChanged(TurnState.SPEAKING),
        SpeechStarted(),
        SpeechFinished(),
        StateChanged(TurnState.LISTENING),
    ]


def test_multiple_turns_have_no_duplicate_events() -> None:
    observer = RecordingObserver()
    runtime = make_runtime(observer)
    asyncio.run(runtime.run_turn())
    asyncio.run(runtime.run_turn())

    first = turn_event_signature(observer.events[:8])
    second = turn_event_signature(observer.events[8:])
    assert first == second
    assert len(observer.events) == 16


def test_safe_error_is_emitted_and_original_exception_propagates() -> None:
    class FailingSTT:
        async def transcribe(self, audio):
            raise RuntimeError("Authorization: Bearer extremely-secret-token")

    observer = RecordingObserver()
    runtime = make_runtime(observer, stt=FailingSTT())

    with pytest.raises(RuntimeError, match="extremely-secret-token"):
        asyncio.run(runtime.run_turn())

    assert observer.events == [
        StateChanged(TurnState.TRANSCRIBING),
        ApplicationError("transcription", "transcription failed"),
    ]
    assert "extremely-secret-token" not in repr(observer.events)


def test_observer_exception_propagates_without_continuing_turn() -> None:
    class FailingObserver:
        def publish(self, event):
            raise LookupError("frontend failed")

    runtime = make_runtime(FailingObserver())
    with pytest.raises(LookupError, match="frontend failed"):
        asyncio.run(runtime.run_turn())


@pytest.mark.parametrize("failing_event", [CharacterLoaded, StateChanged])
def test_startup_observer_failure_closes_owned_resources_and_stays_primary(
    tmp_path: Path, failing_event: type
) -> None:
    character = CharacterDefinition(
        id="amy",
        name="Amy",
        system_prompt="Prompt",
        package_root=tmp_path,
        llm=LLMPreference("fake-llm", "model"),
        tts=TTSPreference("fake-tts", "voice"),
    )
    llms: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    ttss: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()
    llms.register("fake-llm", lambda preference, config: FakeLLM())
    ttss.register("fake-tts", lambda preference, config: FakeTTS())

    class ClosingSource(FakeSource):
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("cleanup failed")

    class FailingStartupObserver:
        def publish(self, event) -> None:
            if isinstance(event, failing_event):
                raise LookupError("startup observer failed")

    source = ClosingSource()
    application = compose_character_runtime(
        character,
        ApplicationConfig("whisper"),
        llm_registry=llms,
        tts_registry=ttss,
        factories=CompositionFactories(
            audio_source=lambda: source,
            vad=FakeVAD,
            stt=lambda path: FakeSTT(),
            audio_output=FakeOutput,
        ),
        event_observers=(FailingStartupObserver(),),
    )

    with pytest.raises(LookupError, match="startup observer failed"):
        asyncio.run(application.run())
    assert source.close_calls == 1


def test_speech_events_surround_audible_playback_not_synthesis() -> None:
    timeline = []

    class InstrumentedObserver(RecordingObserver):
        def publish(self, event) -> None:
            super().publish(event)
            if isinstance(event, SpeechStarted):
                timeline.append("SpeechStarted")
            elif isinstance(event, SpeechFinished):
                timeline.append("SpeechFinished")

    class InstrumentedTTS(FakeTTS):
        async def synthesize(self, text):
            timeline.append("TTS synthesize")
            return await super().synthesize(text)

    class InstrumentedOutput(FakeOutput):
        async def play(self, audio):
            timeline.append("AudioOutput.play")

    runtime = make_runtime(
        InstrumentedObserver(), tts=InstrumentedTTS(), output=InstrumentedOutput()
    )
    asyncio.run(runtime.run_turn())

    assert timeline == [
        "TTS synthesize",
        "SpeechStarted",
        "AudioOutput.play",
        "SpeechFinished",
    ]


def test_synthesis_failure_does_not_emit_speech_started() -> None:
    class FailingTTS:
        async def synthesize(self, text):
            raise RuntimeError("synthesis failed")

    observer = RecordingObserver()
    runtime = make_runtime(observer, tts=FailingTTS())
    with pytest.raises(RuntimeError, match="synthesis failed"):
        asyncio.run(runtime.run_turn())

    assert not any(isinstance(event, SpeechStarted) for event in observer.events)
    assert not any(isinstance(event, SpeechFinished) for event in observer.events)


def test_speech_finished_requires_successful_playback_completion() -> None:
    class ControlledOutput:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.complete = asyncio.Event()

        async def play(self, audio):
            self.entered.set()
            await self.complete.wait()

    async def exercise() -> None:
        observer = RecordingObserver()
        output = ControlledOutput()
        runtime = make_runtime(observer, output=output)
        turn = asyncio.create_task(runtime.run_turn())
        await output.entered.wait()

        assert any(isinstance(event, SpeechStarted) for event in observer.events)
        assert not any(isinstance(event, SpeechFinished) for event in observer.events)

        output.complete.set()
        await turn
        assert sum(isinstance(event, SpeechFinished) for event in observer.events) == 1

    asyncio.run(exercise())


def test_failed_playback_does_not_emit_speech_finished() -> None:
    class FailingOutput:
        async def play(self, audio):
            raise RuntimeError("playback failed")

    observer = RecordingObserver()
    runtime = make_runtime(observer, output=FailingOutput())
    with pytest.raises(RuntimeError, match="playback failed"):
        asyncio.run(runtime.run_turn())

    assert sum(isinstance(event, SpeechStarted) for event in observer.events) == 1
    assert not any(isinstance(event, SpeechFinished) for event in observer.events)


def test_cancellation_propagates_without_error_event() -> None:
    class CancellingSTT:
        async def transcribe(self, audio):
            raise asyncio.CancelledError

    observer = RecordingObserver()
    runtime = make_runtime(observer, stt=CancellingSTT())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_turn())
    assert observer.events == [StateChanged(TurnState.TRANSCRIBING)]


def test_character_application_and_frontend_seam(tmp_path: Path) -> None:
    character = CharacterDefinition(
        id="amy",
        name="Amy",
        system_prompt="Prompt",
        package_root=tmp_path,
        visuals={"idle": tmp_path / "idle.png"},
        animations={
            "idle": AnimationDefinition(
                (tmp_path / "idle-0.png", tmp_path / "idle-1.png"), 6.0
            )
        },
        llm=LLMPreference("fake-llm", "model"),
        tts=TTSPreference("fake-tts", "voice"),
    )
    llms: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    ttss: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()
    llms.register("fake-llm", lambda preference, config: FakeLLM())
    ttss.register("fake-tts", lambda preference, config: FakeTTS())

    class FrontendObserver(RecordingObserver):
        def __init__(self) -> None:
            super().__init__()
            self.current_state = None
            self.transcript = None
            self.response = None
            self.speaking = False

        def publish(self, event) -> None:
            super().publish(event)
            if isinstance(event, StateChanged):
                self.current_state = event.state
            elif isinstance(event, TranscriptReady):
                self.transcript = event.transcript
            elif isinstance(event, ResponseReady):
                self.response = event.response
            elif isinstance(event, SpeechStarted):
                self.speaking = True
            elif isinstance(event, SpeechFinished):
                self.speaking = False

    frontend = FrontendObserver()
    application = None

    def completed(result) -> None:
        application.loop.request_stop()

    application = compose_character_runtime(
        character,
        ApplicationConfig("whisper"),
        llm_registry=llms,
        tts_registry=ttss,
        factories=CompositionFactories(
            audio_source=FakeSource,
            vad=FakeVAD,
            stt=lambda path: FakeSTT(),
            audio_output=FakeOutput,
        ),
        on_turn_completed=completed,
        event_observers=(frontend,),
    )
    asyncio.run(application.run())

    assert frontend.events[0] == CharacterLoaded(
        "amy",
        "Amy",
        (("idle", str(tmp_path / "idle.png")),),
        (
            (
                "idle",
                (str(tmp_path / "idle-0.png"), str(tmp_path / "idle-1.png")),
                6.0,
                True,
            ),
        ),
    )
    assert frontend.events[1] == StateChanged(TurnState.LISTENING)
    assert frontend.events[-2:] == [
        StateChanged(TurnState.STOPPED),
        ApplicationStopped(),
    ]
    assert frontend.current_state is TurnState.STOPPED
    assert frontend.transcript == "question 1"
    assert frontend.response == "answer 1"
    assert frontend.speaking is False


def test_publisher_supports_multiple_observers_in_registration_order() -> None:
    calls = []

    class Observer:
        def __init__(self, name):
            self.name = name

        def publish(self, event):
            calls.append((self.name, event))

    event = SpeechStarted()
    EventPublisher((Observer("cli"), Observer("gui"))).publish(event)
    assert calls == [("cli", event), ("gui", event)]
