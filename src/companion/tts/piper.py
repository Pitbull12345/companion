import asyncio
import io
import wave
from collections.abc import Callable
from typing import Protocol

from companion.audio.interfaces import AudioClip
from companion.tts.errors import TTSError


class PiperVoice(Protocol):
    def synthesize_wav(self, text: str, wav_file: wave.Wave_write) -> None: ...


VoiceFactory = Callable[[str, str | None], PiperVoice]


def _load_local_voice(model_path: str, config_path: str | None) -> PiperVoice:
    try:
        from piper import PiperVoice as LocalPiperVoice

        if config_path is None:
            return LocalPiperVoice.load(model_path)
        return LocalPiperVoice.load(model_path, config_path=config_path)
    except Exception as exc:
        raise TTSError(f"could not load local Piper voice {model_path!r}: {exc}") from exc


class PiperTTSProvider:
    """Local Piper adapter with serialized worker-thread synthesis.

    Concurrent calls are supported but serialized because the owned voice may
    not be safe for concurrent use. Cancellation waits for an in-flight worker
    to finish before releasing the voice for another request.
    """

    def __init__(
        self,
        model_path: str,
        *,
        config_path: str | None = None,
        voice_factory: VoiceFactory | None = None,
    ) -> None:
        self._model_path = model_path
        self._config_path = config_path
        self._voice_factory = voice_factory or _load_local_voice
        self._voice: PiperVoice | None = None
        self._worker_lock = asyncio.Lock()

    @staticmethod
    def _read_clip(wav_data: io.BytesIO) -> AudioClip:
        try:
            wav_data.seek(0)
            with wave.open(wav_data, "rb") as reader:
                clip = AudioClip(
                    data=reader.readframes(reader.getnframes()),
                    sample_rate=reader.getframerate(),
                    channels=reader.getnchannels(),
                    sample_width=reader.getsampwidth(),
                )
        except (EOFError, wave.Error) as exc:
            raise TTSError(f"Piper produced malformed audio: {exc}") from exc
        if (
            not clip.data
            or clip.sample_rate <= 0
            or clip.channels <= 0
            or clip.sample_width <= 0
            or len(clip.data) % (clip.channels * clip.sample_width)
        ):
            raise TTSError("Piper produced empty or malformed audio")
        return clip

    def _synthesize_sync(self, text: str) -> AudioClip:
        try:
            if self._voice is None:
                self._voice = self._voice_factory(
                    self._model_path, self._config_path
                )
            wav_data = io.BytesIO()
            writer = wave.open(wav_data, "wb")
            try:
                self._voice.synthesize_wav(text, writer)
            except Exception as exc:
                try:
                    writer.close()
                except Exception:
                    pass
                raise TTSError(f"Piper synthesis failed: {exc}") from exc
            writer.close()
            return self._read_clip(wav_data)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"Piper synthesis failed: {exc}") from exc

    async def synthesize(self, text: str) -> AudioClip:
        if not text.strip():
            raise TTSError("cannot synthesize empty text")
        async with self._worker_lock:
            worker = asyncio.create_task(
                asyncio.to_thread(self._synthesize_sync, text)
            )
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(worker)
                except Exception:
                    pass
                raise
