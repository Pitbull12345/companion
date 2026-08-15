"""Provider-neutral events exposed by the Companion application layer.

Publication is synchronous and ordered. Observers should therefore do only
small, non-blocking work; an observer exception propagates to the publisher.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from companion.runtime.turn import TurnState


@dataclass(frozen=True, slots=True)
class CharacterLoaded:
    character_id: str
    character_name: str
    visuals: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class StateChanged:
    state: TurnState


@dataclass(frozen=True, slots=True)
class TranscriptReady:
    transcript: str


@dataclass(frozen=True, slots=True)
class ResponseReady:
    response: str


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    pass


@dataclass(frozen=True, slots=True)
class SpeechFinished:
    pass


@dataclass(frozen=True, slots=True)
class ApplicationError:
    phase: str
    message: str


@dataclass(frozen=True, slots=True)
class ApplicationStopped:
    pass


ApplicationEvent: TypeAlias = (
    CharacterLoaded
    | StateChanged
    | TranscriptReady
    | ResponseReady
    | SpeechStarted
    | SpeechFinished
    | ApplicationError
    | ApplicationStopped
)


class ApplicationEventObserver(Protocol):
    def publish(self, event: ApplicationEvent) -> None: ...


class EventPublisher:
    """Publish events to each observer inline, in registration order."""

    def __init__(self, observers: Iterable[ApplicationEventObserver] = ()) -> None:
        self._observers = tuple(observers)

    def publish(self, event: ApplicationEvent) -> None:
        for observer in self._observers:
            observer.publish(event)

