import pytest

from companion.runtime.turn import (
    InvalidTurnTransition,
    TurnController,
    TurnState,
)


def test_valid_turn_transitions() -> None:
    controller = TurnController()

    for state in (
        TurnState.TRANSCRIBING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
    ):
        controller.transition_to(state)

    assert controller.state is TurnState.LISTENING


def test_transition_observer_receives_states_in_exact_order() -> None:
    observed: list[TurnState] = []
    controller = TurnController(on_transition=observed.append)

    for state in (
        TurnState.TRANSCRIBING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
    ):
        controller.transition_to(state)

    assert observed == [
        TurnState.TRANSCRIBING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
    ]


def test_invalid_transition_does_not_notify_observer() -> None:
    observed: list[TurnState] = []
    controller = TurnController(on_transition=observed.append)

    with pytest.raises(InvalidTurnTransition):
        controller.transition_to(TurnState.SPEAKING)

    assert observed == []


def test_can_stop_from_an_active_state() -> None:
    controller = TurnController()

    controller.transition_to(TurnState.STOPPED)

    assert controller.state is TurnState.STOPPED


def test_invalid_turn_transition_raises_domain_error() -> None:
    controller = TurnController()

    with pytest.raises(InvalidTurnTransition) as error:
        controller.transition_to(TurnState.SPEAKING)

    assert error.value.current is TurnState.LISTENING
    assert error.value.requested is TurnState.SPEAKING
