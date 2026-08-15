import argparse
import signal
import sys
from collections.abc import Sequence
from typing import Protocol

from companion.application.composition import compose_character_runtime
from companion.application.configuration import (
    add_character_runtime_arguments,
    application_config_from_arguments,
)
from companion.application.errors import CompositionError
from companion.character.errors import CharacterError
from companion.character.loader import load_character


class GuiFrontend(Protocol):
    def run(self, argv: Sequence[str]) -> int: ...

    def request_shutdown(self) -> None: ...


def _run_with_sigint_shutdown(frontend: GuiFrontend) -> int:
    """Run GTK while translating Ctrl-C into its normal shutdown lifecycle."""
    interrupted = False
    previous_handler = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum: int, frame: object | None) -> None:
        del signum, frame
        nonlocal interrupted
        interrupted = True
        frontend.request_shutdown()

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        status = frontend.run([])
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    return 130 if interrupted else status


def build_gui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="companion-gui",
        description="Run Companion as a GTK4 desktop pet.",
    )
    add_character_runtime_arguments(parser)
    return parser


def _validate_gui_arguments(
    parser: argparse.ArgumentParser, arguments: argparse.Namespace
) -> None:
    missing = [
        option
        for option, value in (
            ("--character", arguments.character),
            ("--whisper-model", arguments.whisper_model),
        )
        if value is None
    ]
    if missing:
        parser.error("companion-gui requires " + ", ".join(missing))


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_gui_parser()
    arguments = parser.parse_args(argv)
    _validate_gui_arguments(parser, arguments)
    try:
        from companion.frontend.gtk import GtkPetApplication

        frontend = GtkPetApplication()
        runtime = compose_character_runtime(
            load_character(arguments.character),
            application_config_from_arguments(arguments),
            event_observers=(frontend.observer,),
        )
        frontend.attach_runtime(runtime)
        status = _run_with_sigint_shutdown(frontend)
    except (CompositionError, CharacterError) as exc:
        print(f"Companion configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except ImportError as exc:
        print("Companion GUI requires GTK4 and PyGObject.", file=sys.stderr)
        raise SystemExit(1) from exc
    if status:
        raise SystemExit(status)


if __name__ == "__main__":
    main()
