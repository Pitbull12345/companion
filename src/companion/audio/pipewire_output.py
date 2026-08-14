import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from companion.audio.errors import PlaybackError
from companion.audio.interfaces import AudioClip


class _PlaybackProcess(Protocol):
    returncode: int | None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]: ...

    def terminate(self) -> None: ...

    async def wait(self) -> int: ...


ProcessFactory = Callable[..., Awaitable[_PlaybackProcess]]


class PipeWireAudioOutput:
    """Linux raw-PCM playback routed through PipeWire's default sink.

    Playback calls are serialized. No target node is specified, leaving
    routing and device-rate adaptation to PipeWire and WirePlumber.
    """

    def __init__(
        self,
        *,
        executable: str = "pw-cat",
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self._executable = executable
        self._process_factory = process_factory or asyncio.create_subprocess_exec
        self._playback_lock = asyncio.Lock()

    @staticmethod
    def _format(sample_width: int) -> str:
        try:
            return {1: "s8", 2: "s16", 4: "s32"}[sample_width]
        except KeyError as exc:
            raise PlaybackError(
                f"unsupported PipeWire PCM sample width {sample_width}"
            ) from exc

    @classmethod
    def _validate_clip(cls, audio: AudioClip) -> None:
        if not audio.data:
            raise PlaybackError("cannot play empty audio")
        if audio.sample_rate <= 0:
            raise PlaybackError("audio sample rate must be positive")
        if audio.channels <= 0:
            raise PlaybackError("audio channel count must be positive")
        cls._format(audio.sample_width)
        if len(audio.data) % (audio.channels * audio.sample_width):
            raise PlaybackError("malformed audio: byte length is not frame-aligned")

    @staticmethod
    async def _terminate_and_wait(process: _PlaybackProcess) -> None:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        await process.wait()

    async def play(self, audio: AudioClip) -> None:
        self._validate_clip(audio)
        command = (
            self._executable,
            "--playback",
            "--raw",
            "--rate",
            str(audio.sample_rate),
            "--channels",
            str(audio.channels),
            "--format",
            self._format(audio.sample_width),
            "-",
        )

        async with self._playback_lock:
            try:
                process = await self._process_factory(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except asyncio.CancelledError:
                raise
            except FileNotFoundError as exc:
                raise PlaybackError(
                    f"PipeWire playback client {self._executable!r} is unavailable"
                ) from exc
            except Exception as exc:
                raise PlaybackError(
                    f"could not start PipeWire playback: {exc}"
                ) from exc

            try:
                _stdout, stderr = await process.communicate(input=audio.data)
            except asyncio.CancelledError:
                try:
                    await self._terminate_and_wait(process)
                except Exception:
                    pass
                raise
            except Exception as exc:
                try:
                    await self._terminate_and_wait(process)
                except Exception:
                    pass
                raise PlaybackError(f"PipeWire playback failed: {exc}") from exc

            if process.returncode != 0:
                detail = stderr.decode(errors="replace").strip()
                suffix = f": {detail}" if detail else ""
                raise PlaybackError(
                    f"PipeWire playback exited with status {process.returncode}{suffix}"
                )
