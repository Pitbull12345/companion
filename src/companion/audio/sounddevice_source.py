import asyncio
from collections import deque
from collections.abc import Callable
from threading import Lock
from typing import Any, Protocol

from companion.audio.errors import AudioError
from companion.audio.interfaces import AudioFrame


class _InputStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


StreamFactory = Callable[..., _InputStream]


class SoundDeviceAudioSource:
    """Microphone-backed source of signed 16-bit PCM audio frames."""

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        channels: int = 1,
        blocksize: int = 0,
        device: int | str | None = None,
        max_buffered_frames: int = 32,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        if max_buffered_frames < 1:
            raise ValueError("max_buffered_frames must be at least 1")
        self._sample_rate = sample_rate
        self._channels = channels
        self._blocksize = blocksize
        self._device = device
        self._max_buffered_frames = max_buffered_frames
        self._stream_factory = stream_factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._data_ready: asyncio.Event | None = None
        self._buffer: deque[AudioFrame | AudioError] = deque()
        self._buffer_lock = Lock()
        self._notification_pending = False
        self._callback_error: AudioError | None = None
        self._closed = False
        self._stream: _InputStream | None = None

    @staticmethod
    def _default_stream_factory() -> StreamFactory:
        try:
            import sounddevice
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise AudioError("sounddevice is not available") from exc
        return sounddevice.RawInputStream

    async def start(self) -> None:
        """Open capture and bind callback notifications to the current loop."""
        if self._closed:
            raise AudioError("cannot start a closed audio source")
        current_loop = asyncio.get_running_loop()
        if self._stream is not None:
            if current_loop is not self._loop:
                raise AudioError("audio source is bound to a different event loop")
            return

        self._loop = current_loop
        self._data_ready = asyncio.Event()
        factory = self._stream_factory or self._default_stream_factory()
        options: dict[str, Any] = {
            "samplerate": self._sample_rate,
            "channels": self._channels,
            "dtype": "int16",
            "blocksize": self._blocksize,
            "callback": self._audio_callback,
        }
        if self._device is not None:
            options["device"] = self._device

        try:
            stream = factory(**options)
            self._stream = stream
            stream.start()
        except Exception as exc:
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._closed = True
            raise AudioError(f"could not open microphone input stream: {exc}") from exc

    def _audio_callback(
        self, indata: Any, frames: int, time: Any, status: Any
    ) -> None:
        del frames, time
        loop = self._loop
        if self._closed or loop is None:
            return
        with self._buffer_lock:
            if self._callback_error is not None:
                return
            if status:
                item: AudioFrame | AudioError = AudioError(
                    f"microphone input stream failure: {status}"
                )
                self._callback_error = item
                self._buffer.clear()
            else:
                item = AudioFrame(
                    data=bytes(indata),
                    sample_rate=self._sample_rate,
                    channels=self._channels,
                    sample_width=2,
                )
                if len(self._buffer) == self._max_buffered_frames:
                    self._buffer.popleft()
            self._buffer.append(item)
            if self._notification_pending:
                return
            self._notification_pending = True
        try:
            loop.call_soon_threadsafe(self._notify_reader)
        except RuntimeError:
            with self._buffer_lock:
                self._notification_pending = False

    def _notify_reader(self) -> None:
        if self._data_ready is not None:
            self._data_ready.set()
        with self._buffer_lock:
            self._notification_pending = False

    async def read_frame(self) -> AudioFrame:
        if self._closed:
            raise AudioError("cannot read from a closed audio source")
        await self.start()
        assert self._data_ready is not None
        while True:
            self._data_ready.clear()
            with self._buffer_lock:
                if self._buffer:
                    item = self._buffer.popleft()
                    if self._buffer:
                        self._data_ready.set()
                    if isinstance(item, AudioError):
                        raise item
                    return item
                if self._callback_error is not None:
                    raise self._callback_error
                if self._closed:
                    raise AudioError("audio source closed while waiting for a frame")
            await self._data_ready.wait()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        stream, self._stream = self._stream, None
        error: Exception | None = None
        if stream is not None:
            try:
                stream.stop()
            except Exception as exc:
                error = exc
            try:
                stream.close()
            except Exception as exc:
                error = error or exc
        with self._buffer_lock:
            self._buffer.clear()
        if self._loop is not None and self._data_ready is not None:
            try:
                self._loop.call_soon_threadsafe(self._data_ready.set)
            except RuntimeError:
                pass
        if error is not None:
            raise AudioError(f"could not close microphone input stream: {error}") from error

    def __enter__(self) -> "SoundDeviceAudioSource":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
