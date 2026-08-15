import signal
from pathlib import Path

import pytest

from companion.application.configuration import application_config_from_arguments
from companion.frontend.cli import (
    _run_with_sigint_shutdown,
    _validate_gui_arguments,
    build_gui_parser,
)


def test_gui_configuration_parsing_and_environment_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "speech-secret")
    parser = build_gui_parser()
    arguments = parser.parse_args(
        [
            "--character",
            "/characters/amy",
            "--whisper-model",
            "/models/whisper",
            "--ollama-host",
            "http://ollama.test",
            "--ollama-timeout",
            "12",
            "--openrouter-base-url",
            "https://router.test",
            "--openrouter-timeout",
            "13",
            "--piper-voice-root",
            "/voices",
            "--elevenlabs-base-url",
            "https://speech.test",
            "--elevenlabs-timeout",
            "14",
        ]
    )
    _validate_gui_arguments(parser, arguments)
    config = application_config_from_arguments(arguments)

    assert arguments.character == "/characters/amy"
    assert config.whisper_model_path == "/models/whisper"
    assert config.ollama_host == "http://ollama.test"
    assert config.ollama_timeout == 12
    assert config.openrouter_base_url == "https://router.test"
    assert config.openrouter_timeout == 13
    assert config.piper_voice_root == Path("/voices")
    assert config.elevenlabs_base_url == "https://speech.test"
    assert config.elevenlabs_timeout == 14
    assert config.openrouter_api_key == "router-secret"
    assert config.elevenlabs_api_key == "speech-secret"
    assert "router-secret" not in repr(config)
    assert "speech-secret" not in repr(config)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--whisper-model", "/models/whisper"],
        ["--character", "/characters/amy"],
    ],
)
def test_gui_requires_character_and_whisper_model(arguments: list[str]) -> None:
    parser = build_gui_parser()
    parsed = parser.parse_args(arguments)
    with pytest.raises(SystemExit):
        _validate_gui_arguments(parser, parsed)


def test_sigint_requests_normal_frontend_shutdown_and_returns_130() -> None:
    class Frontend:
        shutdown_requested = False

        def run(self, argv: list[str]) -> int:
            assert argv == []
            handler = signal.getsignal(signal.SIGINT)
            assert callable(handler)
            handler(signal.SIGINT, None)
            return 0

        def request_shutdown(self) -> None:
            self.shutdown_requested = True

    frontend = Frontend()
    previous_handler = signal.getsignal(signal.SIGINT)

    assert _run_with_sigint_shutdown(frontend) == 130
    assert frontend.shutdown_requested
    assert signal.getsignal(signal.SIGINT) is previous_handler


def test_gui_run_preserves_normal_status_and_restores_sigint_handler() -> None:
    class Frontend:
        def run(self, argv: list[str]) -> int:
            assert argv == []
            return 7

        def request_shutdown(self) -> None:
            raise AssertionError("shutdown was not requested")

    previous_handler = signal.getsignal(signal.SIGINT)

    assert _run_with_sigint_shutdown(Frontend()) == 7
    assert signal.getsignal(signal.SIGINT) is previous_handler


def test_gui_run_does_not_swallow_unrelated_exceptions() -> None:
    failure = RuntimeError("GTK failed")

    class Frontend:
        def run(self, argv: list[str]) -> int:
            raise failure

        def request_shutdown(self) -> None:
            raise AssertionError("shutdown was not requested")

    previous_handler = signal.getsignal(signal.SIGINT)

    with pytest.raises(RuntimeError) as raised:
        _run_with_sigint_shutdown(Frontend())

    assert raised.value is failure
    assert signal.getsignal(signal.SIGINT) is previous_handler
