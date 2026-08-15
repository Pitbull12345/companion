import asyncio
import threading
from collections.abc import Callable
from typing import Protocol


class RuntimeApplication(Protocol):
    async def run(self) -> None: ...


class RuntimeWorker:
    """Own exactly one thread and asyncio task for a Companion application."""

    def __init__(
        self,
        application: RuntimeApplication,
        *,
        on_finished: Callable[[BaseException | None], None] | None = None,
    ) -> None:
        self._application = application
        self._on_finished = on_finished
        self._thread = threading.Thread(
            target=self._thread_main,
            name="companion-runtime",
            daemon=False,
        )
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._started = False
        self._stop_requested = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self.failure: BaseException | None = None

    @property
    def thread(self) -> threading.Thread:
        return self._thread

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("runtime worker can only be started once")
            self._started = True
        self._thread.start()

    def cancel(self) -> None:
        with self._lock:
            self._stop_requested = True
            loop = self._loop
            task = self._task
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)

    def join(self, timeout: float | None = None) -> None:
        if self._started:
            self._thread.join(timeout)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run_application())
        except BaseException as exc:
            self.failure = exc
        finally:
            if self._on_finished is not None:
                self._on_finished(self.failure)

    async def _run_application(self) -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(self._application.run(), name="companion-application")
        with self._lock:
            self._loop = loop
            self._task = task
            stop_requested = self._stop_requested
        self._ready.set()
        # Give the application coroutine one turn to enter its lifecycle guard
        # before honoring a stop requested ahead of worker startup. This keeps
        # CharacterApplication resource cleanup reachable.
        await asyncio.sleep(0)
        if stop_requested:
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            with self._lock:
                requested = self._stop_requested
            if not requested:
                raise
        finally:
            with self._lock:
                self._task = None
                self._loop = None
