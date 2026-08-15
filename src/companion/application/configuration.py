import argparse
import os

from companion.application.composition import ApplicationConfig, default_piper_voice_root


def add_character_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--whisper-model",
        help="Path to an installed local faster-whisper model",
    )
    parser.add_argument(
        "--character",
        help="Path to a character package (uses its prompt, LLM model, and TTS voice)",
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
        "--openrouter-base-url",
        default="https://openrouter.ai",
        help="OpenRouter API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--openrouter-timeout",
        type=float,
        default=30.0,
        help="OpenRouter request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--piper-voice-root",
        default=str(default_piper_voice_root()),
        help="Directory containing installed Piper voices (default: %(default)s)",
    )
    parser.add_argument(
        "--elevenlabs-base-url",
        default="https://api.elevenlabs.io",
        help="ElevenLabs API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--elevenlabs-timeout",
        type=float,
        default=30.0,
        help="ElevenLabs request timeout in seconds (default: %(default)s)",
    )


def application_config_from_arguments(arguments: argparse.Namespace) -> ApplicationConfig:
    return ApplicationConfig(
        whisper_model_path=arguments.whisper_model,
        ollama_host=arguments.ollama_host,
        ollama_timeout=arguments.ollama_timeout,
        piper_voice_root=arguments.piper_voice_root,
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
        openrouter_base_url=arguments.openrouter_base_url,
        openrouter_timeout=arguments.openrouter_timeout,
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY"),
        elevenlabs_base_url=arguments.elevenlabs_base_url,
        elevenlabs_timeout=arguments.elevenlabs_timeout,
    )
