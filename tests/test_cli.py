import argparse
from collections.abc import Sequence

import pytest

from companion.cli import _show_state, _show_turn, build_parser, main
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
