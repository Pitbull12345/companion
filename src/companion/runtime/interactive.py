import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol

from companion.runtime.assistant import TurnResult


class TurnRuntime(Protocol):
    async def run_turn(self) -> TurnResult: ...


class AsyncResource(Protocol):
    async def close(self) -> None: ...


class InteractiveTurnLoop:
    """Sequentially run turns using one runtime until stopping or failure.

    The loop retains no completed results. A requested graceful stop takes
    effect after the active turn; cancellation interrupts the active provider
    operation and propagates after owned resources are closed.
    """

    def __init__(
        self,
        runtime: TurnRuntime,
        *,
        resources: Sequence[AsyncResource] = (),
        on_listening: Callable[[], None] | None = None,
        on_turn_completed: Callable[[TurnResult], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._resources = tuple(resources)
        self._on_listening = on_listening
        self._on_turn_completed = on_turn_completed
        self._stop_requested = False
        self._closed = False
        self._close_lock = asyncio.Lock()

    def request_stop(self) -> None:
        self._stop_requested = True

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            first_failure: Exception | None = None
            for resource in reversed(self._resources):
                try:
                    await resource.close()
                except Exception as exc:
                    first_failure = first_failure or exc
            if first_failure is not None:
                raise first_failure

    async def _run_turns(self) -> None:
        while not self._stop_requested:
            if self._on_listening is not None:
                self._on_listening()
            result = await self._runtime.run_turn()
            if self._on_turn_completed is not None:
                self._on_turn_completed(result)

    async def run(self) -> None:
        try:
            await self._run_turns()
        except BaseException:
            try:
                await self.close()
            except Exception:
                # Preserve the turn failure or cancellation as the primary error.
                pass
            raise
        else:
            await self.close()
