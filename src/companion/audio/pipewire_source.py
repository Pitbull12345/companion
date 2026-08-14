import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from companion.audio.errors import AudioError
from companion.audio.interfaces import AudioFrame


class _ProcessStdout(Protocol):
    async def readexactly(self, n: int) -> bytes: ...


class _CaptureProcess(Protocol):
    stdout: _ProcessStdout | None
    returncode: int | None

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    async def communicate(self) -> tuple[bytes, bytes]: ...

    async def wait(self) -> int: ...


ProcessFactory = Callable[..., Awaitable[_CaptureProcess]]


class PipeWireAudioSource:
    """Lazy PipeWire capture from the system default microphone.

    Each read returns 20 ms (320 samples / 640 bytes) of 16 kHz mono signed
    16-bit PCM. Reads go directly to the subprocess pipe and are serialized;
    no permanent background task or additional audio queue is used.
    """

    _SAMPLE_RATE = 16_000
    _CHANNELS = 1
    _SAMPLE_WIDTH = 2
    _FRAME_SAMPLES = 320
    _FRAME_BYTES = _FRAME_SAMPLES * _CHANNELS * _SAMPLE_WIDTH

    def __init__(
        self,
        *,
        executable: str = "pw-cat",
        process_factory: ProcessFactory | None = None,
        shutdown_timeout: float = 1.0,
    ) -> None:
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive")
        self._executable = executable
        self._process_factory = process_factory or asyncio.create_subprocess_exec
        self._shutdown_timeout = shutdown_timeout
        self._process: _CaptureProcess | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()
        self._closed = False
        self._fatal_error: AudioError | None = None

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                raise AudioError("cannot start a closed PipeWire audio source")
            if self._fatal_error is not None:
                raise self._fatal_error
            if self._process is not None:
                return

            command = (
                self._executable,
                "--record",
                "--raw",
                "--rate",
                str(self._SAMPLE_RATE),
                "--channels",
                str(self._CHANNELS),
                "--format",
                "s16",
                "-",
            )
            try:
                process = await self._process_factory(
                    *command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=self._FRAME_BYTES,
                )
            except asyncio.CancelledError:
                raise
            except FileNotFoundError as exc:
                error = AudioError(
                    f"PipeWire capture client {self._executable!r} is unavailable"
                )
                self._fatal_error = error
                raise error from exc
            except Exception as exc:
                error = AudioError(f"could not start PipeWire capture: {exc}")
                self._fatal_error = error
                raise error from exc

            self._process = process
            if process.stdout is None:
                error = AudioError("PipeWire capture stdout is unavailable")
                self._fatal_error = error
                await self._stop_process(suppress_errors=True)
                raise error

    async def _stop_process(self, *, suppress_errors: bool) -> None:
        process, self._process = self._process, None
        if process is None:
            return

        failure: Exception | None = None
        needs_kill = False
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            except Exception as exc:
                failure = exc
                needs_kill = True

        communicate = asyncio.create_task(process.communicate())
        if not needs_kill:
            try:
                await asyncio.wait_for(
                    asyncio.shield(communicate), timeout=self._shutdown_timeout
                )
                return
            except TimeoutError:
                needs_kill = True
            except asyncio.CancelledError:
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(
                        asyncio.shield(communicate), timeout=self._shutdown_timeout
                    )
                except Exception:
                    communicate.cancel()
                    await asyncio.gather(communicate, return_exceptions=True)
                raise
            except Exception as exc:
                failure = exc
                needs_kill = True

        if needs_kill:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except Exception as exc:
                failure = failure or exc
            try:
                await asyncio.wait_for(
                    asyncio.shield(communicate), timeout=self._shutdown_timeout
                )
            except TimeoutError:
                failure = failure or RuntimeError(
                    "PipeWire capture process could not be reaped after kill"
                )
                communicate.cancel()
                await asyncio.gather(communicate, return_exceptions=True)
            except Exception as exc:
                failure = failure or exc

        if failure is not None and not suppress_errors:
            raise AudioError(f"could not close PipeWire capture: {failure}") from failure

    async def _fail(self, error: AudioError) -> None:
        self._fatal_error = error
        await self._stop_process(suppress_errors=True)

    async def read_frame(self) -> AudioFrame:
        if self._closed:
            raise AudioError("cannot read from a closed PipeWire audio source")
        if self._fatal_error is not None:
            raise self._fatal_error
        await self.start()

        async with self._read_lock:
            process = self._process
            if process is None or process.stdout is None:
                error = AudioError("PipeWire capture is not available")
                await self._fail(error)
                raise error
            try:
                data = await process.stdout.readexactly(self._FRAME_BYTES)
            except asyncio.CancelledError:
                await self._stop_process(suppress_errors=True)
                self._closed = True
                raise
            except asyncio.IncompleteReadError as exc:
                if exc.partial:
                    message = (
                        "PipeWire capture returned an incomplete PCM frame "
                        f"({len(exc.partial)} of {self._FRAME_BYTES} bytes)"
                    )
                else:
                    message = "PipeWire capture process exited unexpectedly"
                error = AudioError(message)
                await self._fail(error)
                raise error from exc
            except Exception as exc:
                error = AudioError(f"PipeWire capture read failed: {exc}")
                await self._fail(error)
                raise error from exc

            if len(data) != self._FRAME_BYTES or len(data) % self._SAMPLE_WIDTH:
                error = AudioError("PipeWire capture returned malformed PCM data")
                await self._fail(error)
                raise error
            return AudioFrame(
                data=data,
                sample_rate=self._SAMPLE_RATE,
                channels=self._CHANNELS,
                sample_width=self._SAMPLE_WIDTH,
            )

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            await self._stop_process(suppress_errors=False)
