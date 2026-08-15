from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PureWindowsPath
from typing import cast

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.audio.faster_whisper_stt import FasterWhisperSTTProvider
from companion.audio.interfaces import AudioOutput, AudioSource, STTProvider, VADProvider
from companion.audio.pipewire_output import PipeWireAudioOutput
from companion.audio.pipewire_source import PipeWireAudioSource
from companion.audio.silero_vad import SileroVADProvider
from companion.application.errors import CompositionError
from companion.events import (
    ApplicationEventObserver,
    ApplicationStopped,
    CharacterLoaded,
    EventPublisher,
    StateChanged,
)
from companion.application.registry import LLMProviderRegistry, TTSProviderRegistry
from companion.character.definition import CharacterDefinition, LLMPreference, TTSPreference
from companion.llm.ollama import OllamaLLMProvider
from companion.llm.openrouter import OpenRouterLLMProvider
from companion.llm.router import LLMRouter
from companion.memory.manager import MemoryManager
from companion.runtime.assistant import AssistantRuntime, TurnResult
from companion.runtime.interactive import AsyncResource, InteractiveTurnLoop
from companion.runtime.turn import TurnController, TurnState
from companion.tts.piper import PiperTTSProvider
from companion.tts.elevenlabs import ElevenLabsTTSProvider, PCM_SAMPLE_RATES


def default_piper_voice_root() -> Path:
    return Path.home() / ".local" / "share" / "companion" / "voices" / "piper"


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    whisper_model_path: str | Path
    ollama_host: str = "http://localhost:11434"
    ollama_timeout: float | None = None
    piper_voice_root: Path = field(default_factory=default_piper_voice_root)
    openrouter_api_key: str | None = field(default=None, repr=False)
    openrouter_base_url: str = "https://openrouter.ai"
    openrouter_timeout: float = 30.0
    elevenlabs_api_key: str | None = field(default=None, repr=False)
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    elevenlabs_timeout: float = 30.0
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_output_format: str = "pcm_24000"

    def __post_init__(self) -> None:
        object.__setattr__(self, "piper_voice_root", Path(self.piper_voice_root))
        if not str(self.whisper_model_path):
            raise CompositionError("Whisper model path is required")
        if not self.ollama_host:
            raise CompositionError("Ollama host is required")
        if self.ollama_timeout is not None and self.ollama_timeout <= 0:
            raise CompositionError("Ollama timeout must be positive")


@dataclass(frozen=True, slots=True)
class PiperVoiceFiles:
    model_path: Path
    config_path: Path | None


class PiperVoiceResolver:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    def resolve(self, voice: str) -> PiperVoiceFiles:
        reference = PurePath(voice)
        if (
            not voice
            or reference.is_absolute()
            or PureWindowsPath(voice).is_absolute()
            or len(reference.parts) != 1
            or reference.name in {".", ".."}
        ):
            raise CompositionError(f"invalid Piper voice identifier {voice!r}")

        model = (self._root / f"{voice}.onnx").resolve()
        config = (self._root / f"{voice}.onnx.json").resolve()
        if not model.is_relative_to(self._root) or not config.is_relative_to(self._root):
            raise CompositionError(f"Piper voice {voice!r} escapes the configured root")
        if not model.is_file():
            raise CompositionError(f"Piper voice model not found for {voice!r}: {model}")
        if model.is_symlink() and not model.resolve().is_relative_to(self._root):
            raise CompositionError(f"Piper voice {voice!r} escapes the configured root")
        if config.exists():
            if not config.is_file() or not config.resolve().is_relative_to(self._root):
                raise CompositionError(f"Piper voice config for {voice!r} is unsafe")
            resolved_config: Path | None = config
        else:
            resolved_config = None
        return PiperVoiceFiles(model, resolved_config)


def _reject_settings(kind: str, settings: object) -> None:
    if settings:
        names = ", ".join(sorted(settings))  # type: ignore[arg-type]
        raise CompositionError(f"unsupported {kind} character settings: {names}")


def _build_ollama(preference: LLMPreference, config: ApplicationConfig):
    _reject_settings("Ollama", preference.settings)
    return OllamaLLMProvider(
        preference.model, host=config.ollama_host, timeout=config.ollama_timeout
    )


def _build_openrouter(preference: LLMPreference, config: ApplicationConfig):
    _reject_settings("OpenRouter", preference.settings)
    if not config.openrouter_api_key:
        raise CompositionError("OPENROUTER_API_KEY is required for OpenRouter")
    if not config.openrouter_base_url:
        raise CompositionError("OpenRouter base URL is required")
    if config.openrouter_timeout <= 0:
        raise CompositionError("OpenRouter timeout must be positive")
    return OpenRouterLLMProvider(
        preference.model,
        config.openrouter_api_key,
        base_url=config.openrouter_base_url,
        timeout=config.openrouter_timeout,
    )


def _build_piper(preference: TTSPreference, config: ApplicationConfig):
    _reject_settings("Piper", preference.settings)
    voice = PiperVoiceResolver(config.piper_voice_root).resolve(preference.voice)
    return PiperTTSProvider(
        str(voice.model_path),
        config_path=None if voice.config_path is None else str(voice.config_path),
    )


def _build_elevenlabs(preference: TTSPreference, config: ApplicationConfig):
    _reject_settings("ElevenLabs", preference.settings)
    if not config.elevenlabs_api_key:
        raise CompositionError("ELEVENLABS_API_KEY is required for ElevenLabs")
    if not config.elevenlabs_base_url:
        raise CompositionError("ElevenLabs base URL is required")
    if config.elevenlabs_timeout <= 0:
        raise CompositionError("ElevenLabs timeout must be positive")
    if not config.elevenlabs_model_id:
        raise CompositionError("ElevenLabs model ID is required")
    if config.elevenlabs_output_format not in PCM_SAMPLE_RATES:
        raise CompositionError(
            f"unsupported ElevenLabs PCM output format {config.elevenlabs_output_format!r}"
        )
    return ElevenLabsTTSProvider(
        preference.voice,
        config.elevenlabs_api_key,
        model_id=config.elevenlabs_model_id,
        base_url=config.elevenlabs_base_url,
        timeout=config.elevenlabs_timeout,
        output_format=config.elevenlabs_output_format,
    )


def create_default_llm_registry() -> LLMProviderRegistry[ApplicationConfig]:
    registry: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    registry.register("ollama", _build_ollama)
    registry.register("openrouter", _build_openrouter)
    return registry


def create_default_tts_registry() -> TTSProviderRegistry[ApplicationConfig]:
    registry: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()
    registry.register("piper", _build_piper)
    registry.register("elevenlabs", _build_elevenlabs)
    return registry


@dataclass(frozen=True, slots=True)
class CompositionFactories:
    audio_source: Callable[[], AudioSource] = PipeWireAudioSource
    vad: Callable[[], VADProvider] = SileroVADProvider
    stt: Callable[[str], STTProvider] = FasterWhisperSTTProvider
    audio_output: Callable[[], AudioOutput] = PipeWireAudioOutput


@dataclass(frozen=True, slots=True)
class CharacterApplication:
    character: CharacterDefinition
    runtime: AssistantRuntime
    loop: InteractiveTurnLoop
    conversation: ConversationManager
    turn_controller: TurnController
    events: EventPublisher

    async def run(self) -> None:
        try:
            self.events.publish(
                CharacterLoaded(
                    self.character.id,
                    self.character.name,
                    tuple(
                        (name, str(path))
                        for name, path in sorted(self.character.visuals.items())
                    ),
                )
            )
            self.events.publish(StateChanged(self.turn_controller.state))
        except BaseException:
            try:
                await self.loop.close()
            except BaseException:
                # Startup publication is the primary failure. Cleanup is still
                # attempted, but cannot replace the observer exception.
                pass
            raise
        try:
            await self.loop.run()
        finally:
            if self.turn_controller.state is not TurnState.STOPPED:
                self.turn_controller.transition_to(TurnState.STOPPED)
            self.events.publish(ApplicationStopped())


def compose_character_runtime(
    character: CharacterDefinition,
    config: ApplicationConfig,
    *,
    llm_registry: LLMProviderRegistry[ApplicationConfig] | None = None,
    tts_registry: TTSProviderRegistry[ApplicationConfig] | None = None,
    factories: CompositionFactories | None = None,
    on_listening: Callable[[], None] | None = None,
    on_turn_completed: Callable[[TurnResult], None] | None = None,
    on_transition: Callable[[TurnState], None] | None = None,
    event_observers: tuple[ApplicationEventObserver, ...] = (),
) -> CharacterApplication:
    if character.llm is None:
        raise CompositionError(f"character {character.id!r} has no LLM preference")
    if character.tts is None:
        raise CompositionError(f"character {character.id!r} has no TTS preference")

    llm = (llm_registry or create_default_llm_registry()).create(
        character.llm, config
    )
    tts = (tts_registry or create_default_tts_registry()).create(
        character.tts, config
    )
    builders = factories or CompositionFactories()
    conversation = ConversationManager()
    events = EventPublisher(event_observers)

    def report_transition(state: TurnState) -> None:
        events.publish(StateChanged(state))
        # Preserve the legacy turn-progress callback, which historically
        # described only turn transitions and did not receive application stop.
        if on_transition is not None and state is not TurnState.STOPPED:
            on_transition(state)

    controller = TurnController(on_transition=report_transition)
    vad = builders.vad()
    stt = builders.stt(str(config.whisper_model_path))
    output = builders.audio_output()
    # The owned source is lazy and deliberately created last, after every
    # configurable builder that can fail during composition.
    source = builders.audio_source()
    runtime = AssistantRuntime(
        audio_source=source,
        vad=vad,
        stt=stt,
        context_builder=ContextBuilder(character.system_prompt, conversation, MemoryManager()),
        llm=LLMRouter(llm),
        tts=tts,
        audio_output=output,
        conversation=conversation,
        turn_controller=controller,
        event_observer=events,
    )
    owned_resources: list[AsyncResource] = [source]
    if callable(getattr(llm, "close", None)):
        owned_resources.append(cast(AsyncResource, llm))
    if callable(getattr(tts, "close", None)) and all(
        resource is not tts for resource in owned_resources
    ):
        owned_resources.append(cast(AsyncResource, tts))
    loop = InteractiveTurnLoop(
        runtime,
        resources=owned_resources,
        on_listening=on_listening,
        on_turn_completed=on_turn_completed,
    )
    return CharacterApplication(character, runtime, loop, conversation, controller, events)
