import argparse
from collections.abc import Sequence
from pathlib import Path

import pytest

from companion.application.errors import CompositionError
from companion.cli import _show_state, _show_turn, build_application, build_parser, main
from companion.runtime.assistant import TurnResult
from companion.runtime.turn import TurnState


def configured_arguments() -> list[str]:
    return [
        "--whisper-model",
        "/models/whisper",
        "--ollama-model",
        "qwen-local",
        "--ollama-host",
        "http://ollama.internal:11434",
        "--piper-model",
        "/voices/amy.onnx",
        "--piper-config",
        "/voices/amy.json",
        "--system-prompt",
        "Be concise.",
    ]


def test_parser_accepts_local_provider_configuration() -> None:
    arguments = build_parser().parse_args(configured_arguments())

    assert arguments.whisper_model == "/models/whisper"
    assert arguments.ollama_model == "qwen-local"
    assert arguments.ollama_host == "http://ollama.internal:11434"
    assert arguments.piper_model == "/voices/amy.onnx"
    assert arguments.piper_config == "/voices/amy.json"
    assert arguments.system_prompt == "Be concise."


def test_parser_accepts_character_and_machine_configuration() -> None:
    arguments = build_parser().parse_args(
        [
            "--character",
            "/characters/amy",
            "--whisper-model",
            "/models/whisper",
            "--ollama-host",
            "http://ollama.internal:11434",
            "--piper-voice-root",
            "/voices",
        ]
    )

    assert arguments.character == "/characters/amy"
    assert arguments.whisper_model == "/models/whisper"
    assert arguments.ollama_host == "http://ollama.internal:11434"
    assert arguments.piper_voice_root == "/voices"
    assert arguments.ollama_model is None
    assert arguments.piper_model is None


def test_character_application_loads_package_and_delegates_to_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = tmp_path / "character"
    package.mkdir()
    (package / "character.toml").write_text(
        """
id = "amy"
name = "Amy"
system_prompt = "You are Amy."

[llm]
provider = "ollama"
model = "character-model"

[tts]
provider = "piper"
voice = "character-voice"
"""
    )
    captured = []
    expected_application = object()

    def fake_compose(character, config, **callbacks):
        captured.append((character, config, callbacks))
        return expected_application

    monkeypatch.setattr("companion.cli.compose_character_runtime", fake_compose)
    arguments = build_parser().parse_args(
        [
            "--character",
            str(package),
            "--whisper-model",
            "/models/whisper",
            "--ollama-host",
            "http://ollama.internal:11434",
            "--ollama-timeout",
            "45",
            "--piper-voice-root",
            "/voices/piper",
        ]
    )

    assert build_application(arguments) is expected_application
    character, config, callbacks = captured[0]
    assert character.system_prompt == "You are Amy."
    assert character.llm.provider == "ollama"
    assert character.llm.model == "character-model"
    assert character.tts.provider == "piper"
    assert character.tts.voice == "character-voice"
    assert config.whisper_model_path == "/models/whisper"
    assert config.ollama_host == "http://ollama.internal:11434"
    assert config.ollama_timeout == 45
    assert config.piper_voice_root == Path("/voices/piper")
    assert callbacks["on_listening"] is not None
    assert callbacks["on_turn_completed"] is not None
    assert callbacks["on_transition"] is not None


def test_main_runs_injected_application_without_real_providers() -> None:
    captured: list[argparse.Namespace] = []

    class FakeApplication:
        def __init__(self) -> None:
            self.run_calls = 0

        async def run(self) -> None:
            self.run_calls += 1

    application = FakeApplication()

    def factory(arguments: argparse.Namespace) -> FakeApplication:
        captured.append(arguments)
        return application

    main(configured_arguments(), application_factory=factory)

    assert application.run_calls == 1
    assert captured[0].whisper_model == "/models/whisper"


def test_cli_prints_provider_neutral_turn_progress_and_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for state in (
        TurnState.TRANSCRIBING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
    ):
        _show_state(state)
    _show_turn(TurnResult("hello", "hi there"))

    assert capsys.readouterr().out.splitlines() == [
        "Transcribing...",
        "Thinking...",
        "Speaking...",
        "You: hello",
        "Companion: hi there",
    ]


def test_main_reports_initialization_failure_concisely(capsys: pytest.CaptureFixture[str]) -> None:
    failure = RuntimeError("configuration failed")

    def factory(arguments: argparse.Namespace) -> None:
        del arguments
        raise failure

    with pytest.raises(SystemExit) as raised:
        main(configured_arguments(), application_factory=factory)

    assert raised.value.code == 1
    assert "Companion failed: configuration failed" in capsys.readouterr().err


def test_main_reports_composition_error_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def factory(arguments: argparse.Namespace) -> None:
        del arguments
        raise CompositionError("unsupported TTS provider 'elevenlabs'")

    with pytest.raises(SystemExit) as raised:
        main(configured_arguments(), application_factory=factory)

    assert raised.value.code == 1
    error = capsys.readouterr().err
    assert (
        "Companion configuration error: unsupported TTS provider 'elevenlabs'"
        in error
    )
    assert "Traceback" not in error


def test_unsupported_character_provider_is_concise_without_real_providers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = tmp_path / "character"
    package.mkdir()
    (package / "character.toml").write_text(
        """
id = "amy"
name = "Amy"
system_prompt = "You are Amy."

[llm]
provider = "ollama"
model = "model"

[tts]
provider = "elevenlabs"
voice = "voice"
"""
    )

    def reject_provider(character, config, **callbacks):
        del character, config, callbacks
        raise CompositionError("unsupported TTS provider 'elevenlabs'")

    monkeypatch.setattr("companion.cli.compose_character_runtime", reject_provider)
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "--character",
                str(package),
                "--whisper-model",
                "/models/whisper",
            ]
        )

    assert raised.value.code == 1
    error = capsys.readouterr().err
    assert (
        "Companion configuration error: unsupported TTS provider 'elevenlabs'"
        in error
    )
    assert "Traceback" not in error


def test_character_mode_rejects_ambiguous_character_owned_overrides(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "--character",
                "/characters/amy",
                "--whisper-model",
                "/models/whisper",
                "--ollama-model",
                "override",
            ],
            application_factory=lambda arguments: None,
        )

    assert raised.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_main_treats_keyboard_interrupt_as_normal_shutdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class InterruptedApplication:
        async def run(self) -> None:
            raise KeyboardInterrupt

    main(
        configured_arguments(),
        application_factory=lambda arguments: InterruptedApplication(),
    )

    error = capsys.readouterr().err
    assert "Companion stopped." in error
    assert "Traceback" not in error


def test_required_model_arguments_are_enforced(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main([], application_factory=lambda arguments: None)

    assert raised.value.code == 2
    error = capsys.readouterr().err
    assert "--whisper-model" in error
    assert "--ollama-model" in error
    assert "--piper-model" in error
