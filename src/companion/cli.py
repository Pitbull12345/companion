import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Protocol

from companion.agent.context import ContextBuilder
from companion.agent.conversation import ConversationManager
from companion.audio.faster_whisper_stt import FasterWhisperSTTProvider
from companion.audio.pipewire_output import PipeWireAudioOutput
from companion.audio.pipewire_source import PipeWireAudioSource
from companion.audio.silero_vad import SileroVADProvider
from companion.application.composition import (
    ApplicationConfig,
    CharacterApplication,
    compose_character_runtime,
    default_piper_voice_root,
)
from companion.application.errors import CompositionError
from companion.character.errors import CharacterError
from companion.character.loader import load_character
from companion.llm.ollama import OllamaLLMProvider
from companion.llm.router import LLMRouter
from companion.memory.manager import MemoryManager
from companion.runtime.assistant import AssistantRuntime, TurnResult
from companion.runtime.interactive import InteractiveTurnLoop
from companion.runtime.turn import TurnController, TurnState
from companion.tts.piper import PiperTTSProvider


class InteractiveApplication(Protocol):
    async def run(self) -> None: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="companion",
        description="Run Companion's local interactive speech loop.",
    )
    parser.add_argument(
        "--whisper-model",
        required=False,
        help="Path to an installed local faster-whisper model",
    )
    parser.add_argument(
        "--character",
        help="Path to a character package (uses its prompt, LLM model, and TTS voice)",
    )
    parser.add_argument(
        "--ollama-model",
        required=False,
        help="Name of an already-installed Ollama model",
    )
    parser.add_argument(
        "--ollama-host",
        default="http://localhost:11434",
        help="Ollama server URL (default: %(default)s)",
    )
    parser.add_argument(
        "--ollama-timeout",
        type=float,
        help="Optional Ollama request timeout in seconds",
    )
    parser.add_argument(
        "--piper-model",
        required=False,
        help="Path to an installed local Piper ONNX voice",
    )
    parser.add_argument(
        "--piper-config",
        help="Optional path to the Piper voice JSON configuration",
    )
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="System prompt for the conversation",
    )
    parser.add_argument(
        "--piper-voice-root",
        default=str(default_piper_voice_root()),
        help="Directory containing installed Piper voices (default: %(default)s)",
    )
    return parser


def _show_listening() -> None:
    print("Listening...", flush=True)


def _show_state(state: TurnState) -> None:
    labels = {
        TurnState.TRANSCRIBING: "Transcribing...",
        TurnState.THINKING: "Thinking...",
        TurnState.SPEAKING: "Speaking...",
    }
    if state in labels:
        print(labels[state], flush=True)


def _show_turn(result: TurnResult) -> None:
    print(f"You: {result.transcript}", flush=True)
    print(f"Companion: {result.response}", flush=True)


def _build_explicit_application(arguments: argparse.Namespace) -> InteractiveTurnLoop:
    audio_source = PipeWireAudioSource()
    conversation = ConversationManager()
    turn_controller = TurnController(on_transition=_show_state)
    runtime = AssistantRuntime(
        audio_source=audio_source,
        vad=SileroVADProvider(),
        stt=FasterWhisperSTTProvider(arguments.whisper_model),
        context_builder=ContextBuilder(
            arguments.system_prompt
            or "You are Companion, a helpful local voice assistant.",
            conversation,
            MemoryManager(),
        ),
        llm=LLMRouter(
            OllamaLLMProvider(
                arguments.ollama_model,
                host=arguments.ollama_host,
                timeout=arguments.ollama_timeout,
            )
        ),
        tts=PiperTTSProvider(
            arguments.piper_model,
            config_path=arguments.piper_config,
        ),
        audio_output=PipeWireAudioOutput(),
        conversation=conversation,
        turn_controller=turn_controller,
    )
    return InteractiveTurnLoop(
        runtime,
        resources=(audio_source,),
        on_listening=_show_listening,
        on_turn_completed=_show_turn,
    )


def build_application(arguments: argparse.Namespace) -> InteractiveTurnLoop | CharacterApplication:
    if arguments.character is None:
        return _build_explicit_application(arguments)
    character = load_character(arguments.character)
    return compose_character_runtime(
        character,
        ApplicationConfig(
            whisper_model_path=arguments.whisper_model,
            ollama_host=arguments.ollama_host,
            ollama_timeout=arguments.ollama_timeout,
            piper_voice_root=arguments.piper_voice_root,
        ),
        on_listening=_show_listening,
        on_turn_completed=_show_turn,
        on_transition=_show_state,
    )


def _validate_arguments(
    parser: argparse.ArgumentParser, arguments: argparse.Namespace
) -> None:
    if arguments.character is not None:
        if arguments.whisper_model is None:
            parser.error("character mode requires --whisper-model")
        conflicting = [
            option
            for option, value in (
                ("--ollama-model", arguments.ollama_model),
                ("--piper-model", arguments.piper_model),
                ("--piper-config", arguments.piper_config),
                ("--system-prompt", arguments.system_prompt),
            )
            if value is not None
        ]
        if conflicting:
            parser.error(
                "--character cannot be combined with character-owned options: "
                + ", ".join(conflicting)
            )
        return
    missing = [
        option
        for option, value in (
            ("--whisper-model", arguments.whisper_model),
            ("--ollama-model", arguments.ollama_model),
            ("--piper-model", arguments.piper_model),
        )
        if value is None
    ]
    if missing:
        parser.error("explicit mode requires " + ", ".join(missing))


def main(
    argv: Sequence[str] | None = None,
    *,
    application_factory=build_application,
) -> None:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    _validate_arguments(parser, arguments)
    try:
        application = application_factory(arguments)
        asyncio.run(application.run())
    except KeyboardInterrupt:
        print("\nCompanion stopped.", file=sys.stderr)
    except (CompositionError, CharacterError) as exc:
        print(f"Companion configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        print(f"Companion failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
