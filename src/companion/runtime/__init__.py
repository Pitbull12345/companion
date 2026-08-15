from companion.runtime.turn import InvalidTurnTransition, TurnController, TurnState


def __getattr__(name: str):
    if name in {"AssistantRuntime", "TurnResult"}:
        from companion.runtime.assistant import AssistantRuntime, TurnResult

        return {"AssistantRuntime": AssistantRuntime, "TurnResult": TurnResult}[name]
    raise AttributeError(name)

__all__ = [
    "AssistantRuntime",
    "InvalidTurnTransition",
    "TurnController",
    "TurnResult",
    "TurnState",
]
