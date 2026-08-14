import asyncio
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from companion.audio.errors import STTError
from companion.audio.interfaces import AudioFrame, AudioSegment


class TranscriptionSegment(Protocol):
    text: str


class WhisperModel(Protocol):
    def transcribe(
        self, audio: Any, *, vad_filter: bool
    ) -> tuple[Iterable[TranscriptionSegment], Any]: ...


ModelFactory = Callable[[str, str, str], WhisperModel]


def _load_local_model(
    model_name_or_path: str, device: str, compute_type: str
) -> WhisperModel:
    try:
        from faster_whisper import WhisperModel as FasterWhisperModel

        return FasterWhisperModel(
            model_name_or_path,
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )
    except Exception as exc:
        raise STTError(
            f"could not load local faster-whisper model {model_name_or_path!r}: {exc}"
        ) from exc


class FasterWhisperSTTProvider:
    """Offline faster-whisper adapter with serialized worker-thread inference.

    Concurrent calls are supported but serialized because the owned model may
    not be safe for concurrent use. Model loading, inference, and consumption
    of faster-whisper's lazy segment iterator all occur in the worker thread.
    """

    def __init__(
        self,
        model_name_or_path: str,
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        model_factory: ModelFactory | None = None,
    ) -> None:
        self._model_name_or_path = model_name_or_path
        self._device = device
        self._compute_type = compute_type
        self._model_factory = model_factory or _load_local_model
        self._model: WhisperModel | None = None
        self._worker_lock = asyncio.Lock()

    @staticmethod
    def _validate_frame(frame: AudioFrame) -> None:
        if frame.sample_rate != 16_000:
            raise STTError(
                f"unsupported STT sample rate {frame.sample_rate}; expected 16000 Hz"
            )
        if frame.channels != 1:
            raise STTError(
                f"unsupported STT channel count {frame.channels}; expected mono"
            )
        if frame.sample_width != 2:
            raise STTError(
                f"unsupported STT sample width {frame.sample_width}; expected 2 bytes"
            )
        if len(frame.data) % 2:
            raise STTError("malformed PCM data: byte length is not sample-aligned")

    @classmethod
    def _validated_pcm(cls, audio: AudioSegment) -> bytes:
        if not audio.frames:
            raise STTError("cannot transcribe an empty audio segment")
        for frame in audio.frames:
            cls._validate_frame(frame)
        pcm = b"".join(frame.data for frame in audio.frames)
        if not pcm:
            raise STTError("cannot transcribe an empty audio segment")
        return pcm

    def _transcribe_sync(self, pcm: bytes) -> str:
        try:
            import numpy

            samples = numpy.frombuffer(pcm, dtype="<i2").astype(numpy.float32)
            samples /= 32768.0
            if self._model is None:
                self._model = self._model_factory(
                    self._model_name_or_path, self._device, self._compute_type
                )
            segments, _info = self._model.transcribe(samples, vad_filter=False)
            texts = [segment.text.strip() for segment in segments]
            return " ".join(" ".join(texts).split())
        except STTError:
            raise
        except Exception as exc:
            raise STTError(f"faster-whisper transcription failed: {exc}") from exc

    async def transcribe(self, audio: AudioSegment) -> str:
        pcm = self._validated_pcm(audio)
        async with self._worker_lock:
            worker = asyncio.create_task(asyncio.to_thread(self._transcribe_sync, pcm))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(worker)
                except Exception:
                    pass
                raise
