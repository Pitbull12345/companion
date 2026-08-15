"""Public application namespace for Companion's provider-neutral events."""

from companion.events import (
    ApplicationError,
    ApplicationEvent,
    ApplicationEventObserver,
    ApplicationStopped,
    CharacterLoaded,
    EventPublisher,
    ResponseReady,
    SpeechFinished,
    SpeechStarted,
    StateChanged,
    TranscriptReady,
)

__all__ = [
    "ApplicationError",
    "ApplicationEvent",
    "ApplicationEventObserver",
    "ApplicationStopped",
    "CharacterLoaded",
    "EventPublisher",
    "ResponseReady",
    "SpeechFinished",
    "SpeechStarted",
    "StateChanged",
    "TranscriptReady",
]
