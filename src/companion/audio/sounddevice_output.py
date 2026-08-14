import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from companion.audio.errors import PlaybackError
from companion.audio.interfaces import AudioClip


class _OutputStream(Protocol):
    def start(self) -> None: ...

    def write(self, data: bytes) -> Any: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


StreamFactory = Callable[..., _OutputStream]
OutputSettingsChecker = Callable[..., None]
DeviceQuery = Callable[..., Any]
Resampler = Callable[[AudioClip, int], AudioClip]


class SoundDeviceAudioOutput:
    """Serialized sounddevice playback using blocking worker-thread writes."""

    def __init__(
        self,
        *,
        device: int | str | None = None,
        stream_factory: StreamFactory | None = None,
        output_settings_checker: OutputSettingsChecker | None = None,
        device_query: DeviceQuery | None = None,
        resampler: Resampler | None = None,
    ) -> None:
        self._device = device
        self._stream_factory = stream_factory
        self._output_settings_checker = output_settings_checker
        self._device_query = device_query
        self._resampler = resampler
        self._worker_lock = asyncio.Lock()

    @staticmethod
    def _default_stream_factory() -> StreamFactory:
        try:
            import sounddevice
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise PlaybackError("sounddevice is not available") from exc
        return sounddevice.RawOutputStream

    @staticmethod
    def _default_output_settings_checker() -> OutputSettingsChecker:
        try:
            import sounddevice
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise PlaybackError("sounddevice is not available") from exc
        return sounddevice.check_output_settings

    @staticmethod
    def _default_device_query() -> DeviceQuery:
        try:
            import sounddevice
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise PlaybackError("sounddevice is not available") from exc
        return sounddevice.query_devices

    @classmethod
    def _default_resampler(cls, audio: AudioClip, target_rate: int) -> AudioClip:
        try:
            import numpy
            import soxr

            dtype = {1: "i1", 2: "<i2", 4: "<i4"}[audio.sample_width]
            samples = numpy.frombuffer(audio.data, dtype=dtype).reshape(
                -1, audio.channels
            )
            resampled = soxr.resample(
                samples,
                audio.sample_rate,
                target_rate,
                quality="HQ",
            )
            pcm = numpy.asarray(resampled, dtype=dtype).tobytes()
            return AudioClip(
                data=pcm,
                sample_rate=target_rate,
                channels=audio.channels,
                sample_width=audio.sample_width,
            )
        except Exception as exc:
            raise PlaybackError(f"audio resampling failed: {exc}") from exc

    @staticmethod
    def _dtype(sample_width: int) -> str:
        try:
            return {1: "int8", 2: "int16", 4: "int32"}[sample_width]
        except KeyError as exc:
            raise PlaybackError(
                f"unsupported audio sample width {sample_width}"
            ) from exc

    @classmethod
    def _validate_clip(cls, audio: AudioClip) -> None:
        if not audio.data:
            raise PlaybackError("cannot play empty audio")
        if audio.sample_rate <= 0:
            raise PlaybackError("audio sample rate must be positive")
        if audio.channels <= 0:
            raise PlaybackError("audio channel count must be positive")
        cls._dtype(audio.sample_width)
        frame_width = audio.channels * audio.sample_width
        if len(audio.data) % frame_width:
            raise PlaybackError("malformed audio: byte length is not frame-aligned")

    def _prepare_clip(self, audio: AudioClip) -> AudioClip:
        checker = self._output_settings_checker
        if checker is None:
            if self._stream_factory is not None:
                return audio
            checker = self._default_output_settings_checker()

        options: dict[str, Any] = {
            "device": self._device,
            "samplerate": audio.sample_rate,
            "channels": audio.channels,
            "dtype": self._dtype(audio.sample_width),
        }
        try:
            checker(**options)
            return audio
        except Exception:
            pass

        query = self._device_query or self._default_device_query()
        try:
            device_info = query(device=self._device, kind="output")
            default_rate = (
                device_info["default_samplerate"]
                if isinstance(device_info, Mapping)
                else device_info.default_samplerate
            )
            target_rate = int(default_rate)
            if target_rate <= 0:
                raise ValueError("default output sample rate is not positive")
        except Exception as exc:
            raise PlaybackError(
                f"could not determine output device sample rate: {exc}"
            ) from exc

        if target_rate == audio.sample_rate:
            raise PlaybackError(
                f"output device rejects its default sample rate {target_rate}"
            )

        resampler = self._resampler or self._default_resampler
        try:
            adapted = resampler(audio, target_rate)
        except PlaybackError:
            raise
        except Exception as exc:
            raise PlaybackError(f"audio resampling failed: {exc}") from exc

        if (
            adapted.sample_rate != target_rate
            or adapted.channels != audio.channels
            or adapted.sample_width != audio.sample_width
        ):
            raise PlaybackError("resampler produced incompatible PCM metadata")
        self._validate_clip(adapted)
        return adapted

    def _play_sync(self, audio: AudioClip) -> None:
        audio = self._prepare_clip(audio)
        factory = self._stream_factory or self._default_stream_factory()
        options: dict[str, Any] = {
            "samplerate": audio.sample_rate,
            "channels": audio.channels,
            "dtype": self._dtype(audio.sample_width),
        }
        if self._device is not None:
            options["device"] = self._device

        stream: _OutputStream | None = None
        try:
            stream = factory(**options)
            stream.start()
            stream.write(audio.data)
            stream.stop()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise PlaybackError(f"audio playback failed: {exc}") from exc
        if stream is not None:
            try:
                stream.close()
            except Exception as exc:
                raise PlaybackError(
                    f"could not close audio output stream: {exc}"
                ) from exc

    async def play(self, audio: AudioClip) -> None:
        self._validate_clip(audio)
        async with self._worker_lock:
            worker = asyncio.create_task(asyncio.to_thread(self._play_sync, audio))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(worker)
                except Exception:
                    pass
                raise
