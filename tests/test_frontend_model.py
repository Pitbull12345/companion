from pathlib import Path

import pytest

from companion.character import AnimationDefinition
from companion.events import (
    ApplicationError,
    ApplicationStopped,
    CharacterLoaded,
    ResponseReady,
    SpeechFinished,
    SpeechStarted,
    StateChanged,
    TranscriptReady,
)
from companion.frontend.model import FrontendError, PetPresentationModel, PetVisualState
from companion.frontend.observer import ScheduledEventObserver
from companion.runtime.turn import TurnState


def png(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


def loaded(tmp_path: Path, *keys: str) -> CharacterLoaded:
    visuals = tuple((key, str(png(tmp_path, f"{key}.png"))) for key in keys)
    return CharacterLoaded("amy", "Amy", visuals)


def animated_loaded(
    tmp_path: Path, *keys: str, visuals: tuple[str, ...] = ()
) -> CharacterLoaded:
    static = tuple((key, str(png(tmp_path, f"static-{key}.png"))) for key in visuals)
    animations = tuple(
        (
            key,
            (
                str(png(tmp_path, f"{key}-0.png")),
                str(png(tmp_path, f"{key}-1.png")),
            ),
            5.0,
            True,
        )
        for key in keys
    )
    return CharacterLoaded("amy", "Amy", static, animations)


def test_character_visuals_and_deterministic_fallbacks(tmp_path: Path) -> None:
    model = PetPresentationModel()
    idle = png(tmp_path, "idle.png")
    listening = png(tmp_path, "listening.png")
    model.apply(
        CharacterLoaded(
            "amy",
            "Amy",
            (("idle", str(idle)), ("listening", str(listening))),
        )
    )

    assert model.character_id == "amy"
    assert model.character_name == "Amy"
    assert model.visual_path == idle
    model.apply(StateChanged(TurnState.LISTENING))
    assert model.visual_path == listening
    model.apply(StateChanged(TurnState.TRANSCRIBING))
    assert model.visual_path == listening
    model.apply(StateChanged(TurnState.THINKING))
    assert model.visual_path == idle
    model.apply(SpeechStarted())
    assert model.visual_path == idle
    model.apply(ApplicationError("runtime", "safe failure"))
    assert model.visual_path == idle


@pytest.mark.parametrize(
    ("event", "state"),
    [
        (StateChanged(TurnState.LISTENING), PetVisualState.LISTENING),
        (StateChanged(TurnState.TRANSCRIBING), PetVisualState.TRANSCRIBING),
        (StateChanged(TurnState.THINKING), PetVisualState.THINKING),
        (SpeechStarted(), PetVisualState.SPEAKING),
        (SpeechFinished(), PetVisualState.LISTENING),
        (ApplicationError("phase", "message"), PetVisualState.ERROR),
        (ApplicationStopped(), PetVisualState.STOPPED),
    ],
)
def test_event_to_presentation_state(tmp_path: Path, event, state) -> None:
    model = PetPresentationModel()
    model.apply(loaded(tmp_path, "idle"))
    model.apply(event)
    assert model.state is state


def test_runtime_speaking_state_waits_for_audible_speech(tmp_path: Path) -> None:
    model = PetPresentationModel()
    model.apply(loaded(tmp_path, "idle", "thinking", "speaking"))
    model.apply(StateChanged(TurnState.THINKING))
    thinking = model.visual_path

    model.apply(StateChanged(TurnState.SPEAKING))
    assert model.state is PetVisualState.THINKING
    assert model.visual_path == thinking

    model.apply(SpeechStarted())
    assert model.state is PetVisualState.SPEAKING
    assert model.visual_path == tmp_path / "speaking.png"
    model.apply(SpeechFinished())
    assert model.state is PetVisualState.LISTENING


def test_transcript_response_and_public_error_are_retained(tmp_path: Path) -> None:
    model = PetPresentationModel()
    model.apply(loaded(tmp_path, "idle"))
    model.apply(TranscriptReady("hello"))
    model.apply(ResponseReady("hi"))
    model.apply(ApplicationError("response", "response failed"))
    assert model.transcript == "hello"
    assert model.response == "hi"
    assert model.error_message == "response failed"


def test_frontend_seam_selects_expected_visual_sequence(tmp_path: Path) -> None:
    model = PetPresentationModel()
    model.apply(loaded(tmp_path, "idle", "listening", "thinking", "speaking"))
    selected = []
    for event in (
        StateChanged(TurnState.LISTENING),
        StateChanged(TurnState.THINKING),
        StateChanged(TurnState.SPEAKING),
        SpeechStarted(),
        SpeechFinished(),
        StateChanged(TurnState.LISTENING),
    ):
        selected.append(model.apply(event).name)
    assert selected == [
        "listening.png",
        "thinking.png",
        "thinking.png",
        "speaking.png",
        "listening.png",
        "listening.png",
    ]


def test_missing_idle_asset_is_concise(tmp_path: Path) -> None:
    model = PetPresentationModel()
    with pytest.raises(FrontendError, match="requires a PNG visual or animation"):
        model.apply(loaded(tmp_path, "thinking"))


@pytest.mark.parametrize("kind", ["missing", "non-png", "invalid-png"])
def test_invalid_visual_path_is_rejected(tmp_path: Path, kind: str) -> None:
    path = tmp_path / ("idle.jpg" if kind == "non-png" else "idle.png")
    if kind == "non-png":
        path.write_bytes(b"image")
    elif kind == "invalid-png":
        path.write_bytes(b"not a png")
    with pytest.raises(FrontendError, match="visual 'idle'"):
        PetPresentationModel().apply(
            CharacterLoaded("amy", "Amy", (("idle", str(path)),))
        )


def test_scheduled_observer_preserves_order_without_mutating_inline() -> None:
    pending = []
    consumed = []
    observer = ScheduledEventObserver(pending.append, consumed.append)
    events = [TranscriptReady("one"), ResponseReady("two"), SpeechStarted()]

    for event in events:
        observer.publish(event)
    assert consumed == []
    assert len(pending) == 3
    for callback in pending:
        assert callback() is False
    assert consumed == events


def test_animation_fallback_precedence_is_interleaved_and_deterministic(
    tmp_path: Path,
) -> None:
    model = PetPresentationModel()
    model.apply(
        animated_loaded(
            tmp_path,
            "idle",
            "listening",
            visuals=("idle", "transcribing"),
        )
    )

    model.apply(StateChanged(TurnState.LISTENING))
    assert isinstance(model.visual_asset, AnimationDefinition)
    assert model.visual_path == tmp_path / "listening-0.png"

    model.apply(StateChanged(TurnState.TRANSCRIBING))
    assert model.visual_asset == tmp_path / "static-transcribing.png"

    model.apply(StateChanged(TurnState.THINKING))
    assert isinstance(model.visual_asset, AnimationDefinition)
    assert model.visual_path == tmp_path / "idle-0.png"


def test_animation_event_sequence_preserves_audible_speaking_semantics(
    tmp_path: Path,
) -> None:
    model = PetPresentationModel()
    model.apply(
        animated_loaded(tmp_path, "idle", "listening", "thinking", "speaking")
    )

    selected = []
    for event in (
        StateChanged(TurnState.LISTENING),
        StateChanged(TurnState.THINKING),
        StateChanged(TurnState.SPEAKING),
        SpeechStarted(),
        SpeechFinished(),
        StateChanged(TurnState.LISTENING),
    ):
        model.apply(event)
        selected.append(model.visual_path.name)

    assert selected == [
        "listening-0.png",
        "thinking-0.png",
        "thinking-0.png",
        "speaking-0.png",
        "listening-0.png",
        "listening-0.png",
    ]
