from enum import Enum


class TurnState(str, Enum):
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    STOPPED = "stopped"


class InvalidTurnTransition(RuntimeError):
    def __init__(self, current: TurnState, requested: TurnState) -> None:
        super().__init__(f"cannot transition from {current.value} to {requested.value}")
        self.current = current
        self.requested = requested


class TurnController:
    _ALLOWED_TRANSITIONS = {
        TurnState.LISTENING: {TurnState.TRANSCRIBING, TurnState.STOPPED},
        TurnState.TRANSCRIBING: {TurnState.THINKING, TurnState.STOPPED},
        TurnState.THINKING: {TurnState.SPEAKING, TurnState.STOPPED},
        TurnState.SPEAKING: {TurnState.LISTENING, TurnState.STOPPED},
        TurnState.STOPPED: set(),
    }

    def __init__(self) -> None:
        self._state = TurnState.LISTENING

    @property
    def state(self) -> TurnState:
        return self._state

    def transition_to(self, state: TurnState) -> None:
        if state not in self._ALLOWED_TRANSITIONS[self._state]:
            raise InvalidTurnTransition(self._state, state)
        self._state = state
