import asyncio
import threading

import pytest

from companion.frontend.runtime_thread import RuntimeWorker


def test_worker_owns_one_thread_starts_once_and_cancels_cleanly() -> None:
    class BlockingApplication:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.exited = threading.Event()
            self.runs = 0

        async def run(self) -> None:
            self.runs += 1
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.exited.set()

    application = BlockingApplication()
    finished = threading.Event()
    results = []
    worker = RuntimeWorker(
        application,
        on_finished=lambda failure: (results.append(failure), finished.set()),
    )
    owned_thread = worker.thread

    worker.start()
    assert application.started.wait(2)
    assert worker.thread is owned_thread
    assert application.runs == 1
    with pytest.raises(RuntimeError, match="only be started once"):
        worker.start()

    worker.cancel()
    worker.join(2)
    assert application.exited.is_set()
    assert finished.is_set()
    assert not worker.is_alive
    assert results == [None]


def test_cancel_before_runtime_task_creation_is_honored() -> None:
    class Application:
        def __init__(self) -> None:
            self.entered = False
            self.cleaned = False

        async def run(self) -> None:
            self.entered = True
            try:
                await asyncio.Event().wait()
            finally:
                self.cleaned = True

    application = Application()
    worker = RuntimeWorker(application)
    worker.cancel()
    worker.start()
    worker.join(2)
    assert not worker.is_alive
    assert worker.failure is None
    assert application.entered
    assert application.cleaned


def test_runtime_failure_is_captured_and_reported() -> None:
    failure = ValueError("runtime failed")
    finished = threading.Event()
    reported = []

    class FailingApplication:
        async def run(self) -> None:
            raise failure

    worker = RuntimeWorker(
        FailingApplication(),
        on_finished=lambda result: (reported.append(result), finished.set()),
    )
    worker.start()
    worker.join(2)

    assert finished.is_set()
    assert worker.failure is failure
    assert reported == [failure]
    assert not worker.is_alive
