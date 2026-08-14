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
        required=True,
        help="Path to an installed local faster-whisper model",
    )
    parser.add_argument(
        "--ollama-model",
        required=True,
        help="Name of an already-installed Ollama model",
    )
    parser.add_argument(
        "--ollama-host",
        default="http://localhost:11434",
        help="Ollama server URL (default: %(default)s)",
    )
    parser.add_argument(
        "--piper-model",
        required=True,
        help="Path to an installed local Piper ONNX voice",
    )
    parser.add_argument(
        "--piper-config",
        help="Optional path to the Piper voice JSON configuration",
    )
    parser.add_argument(
        "--system-prompt",
        default="You are Companion, a helpful local voice assistant.",
        help="System prompt for the conversation",
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


def build_application(arguments: argparse.Namespace) -> InteractiveTurnLoop:
    audio_source = PipeWireAudioSource()
    conversation = ConversationManager()
    turn_controller = TurnController(on_transition=_show_state)
    runtime = AssistantRuntime(
        audio_source=audio_source,
        vad=SileroVADProvider(),
        stt=FasterWhisperSTTProvider(arguments.whisper_model),
        context_builder=ContextBuilder(
            arguments.system_prompt,
            conversation,
            MemoryManager(),
        ),
        llm=LLMRouter(
            OllamaLLMProvider(
                arguments.ollama_model,
                host=arguments.ollama_host,
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


def main(
    argv: Sequence[str] | None = None,
    *,
    application_factory=build_application,
) -> None:
    arguments = build_parser().parse_args(argv)
    try:
        application = application_factory(arguments)
        asyncio.run(application.run())
    except KeyboardInterrupt:
        print("\nCompanion stopped.", file=sys.stderr)
    except Exception as exc:
        print(f"Companion failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
