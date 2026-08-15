from enum import Enum
from pathlib import Path

from companion.events import (
    ApplicationError,
    ApplicationEvent,
    ApplicationStopped,
    CharacterLoaded,
    ResponseReady,
    SpeechFinished,
    SpeechStarted,
    StateChanged,
    TranscriptReady,
)
from companion.runtime.turn import TurnState


class FrontendError(RuntimeError):
    """A concise error safe to show at the graphical application boundary."""


class PetVisualState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    STOPPED = "stopped"


_FALLBACKS = {
    PetVisualState.IDLE: ("idle",),
    PetVisualState.LISTENING: ("listening", "idle"),
    PetVisualState.TRANSCRIBING: ("transcribing", "listening", "idle"),
    PetVisualState.THINKING: ("thinking", "idle"),
    PetVisualState.SPEAKING: ("speaking", "idle"),
    PetVisualState.ERROR: ("error", "idle"),
    PetVisualState.STOPPED: ("idle",),
}


class PetPresentationModel:
    """GTK-independent projection of application events into pet visuals."""

    def __init__(self) -> None:
        self.state = PetVisualState.IDLE
        self.character_id: str | None = None
        self.character_name: str | None = None
        self.transcript: str | None = None
        self.response: str | None = None
        self.error_message: str | None = None
        self._visuals: dict[str, Path] = {}

    @property
    def visual_path(self) -> Path | None:
        for key in _FALLBACKS[self.state]:
            if key in self._visuals:
                return self._visuals[key]
        return None

    def apply(self, event: ApplicationEvent) -> Path | None:
        if isinstance(event, CharacterLoaded):
            visuals = {name: self._validate_png(path, name) for name, path in event.visuals}
            if "idle" not in visuals:
                raise FrontendError(
                    f"character {event.character_id!r} requires a PNG visual named 'idle'"
                )
            self.character_id = event.character_id
            self.character_name = event.character_name
            self._visuals = visuals
            self.state = PetVisualState.IDLE
        elif isinstance(event, StateChanged):
            mapped = {
                TurnState.LISTENING: PetVisualState.LISTENING,
                TurnState.TRANSCRIBING: PetVisualState.TRANSCRIBING,
                TurnState.THINKING: PetVisualState.THINKING,
                TurnState.STOPPED: PetVisualState.STOPPED,
            }.get(event.state)
            # SPEAKING is intentionally ignored until audible playback starts.
            if mapped is not None:
                self.state = mapped
        elif isinstance(event, TranscriptReady):
            self.transcript = event.transcript
        elif isinstance(event, ResponseReady):
            self.response = event.response
        elif isinstance(event, SpeechStarted):
            self.state = PetVisualState.SPEAKING
        elif isinstance(event, SpeechFinished):
            self.state = PetVisualState.LISTENING
        elif isinstance(event, ApplicationError):
            self.error_message = event.message
            self.state = PetVisualState.ERROR
        elif isinstance(event, ApplicationStopped):
            self.state = PetVisualState.STOPPED
        return self.visual_path

    @staticmethod
    def _validate_png(reference: str, name: str) -> Path:
        path = Path(reference)
        if path.suffix.casefold() != ".png":
            raise FrontendError(f"visual {name!r} must reference a PNG file: {path}")
        if not path.is_file():
            raise FrontendError(f"visual {name!r} was not found: {path}")
        try:
            signature = path.read_bytes()[:8]
        except OSError as exc:
            raise FrontendError(f"visual {name!r} could not be read: {path}") from exc
        if signature != b"\x89PNG\r\n\x1a\n":
            raise FrontendError(f"visual {name!r} is not a valid PNG file: {path}")
        return path
