from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AudioFrame:
    data: bytes
    sample_rate: int = 16_000
    channels: int = 1
    sample_width: int = 2


@dataclass(frozen=True, slots=True)
class AudioSegment:
    frames: tuple[AudioFrame, ...]


@dataclass(frozen=True, slots=True)
class AudioClip:
    """Decoded raw PCM audio ready for playback.

    ``data`` contains PCM sample bytes described by ``sample_rate``,
    ``channels``, and ``sample_width``. It must not contain an encoded format
    such as MP3, OGG, or FLAC, or a container such as WAV. Providers and asset
    importers must decode such inputs before constructing an AudioClip.
    """

    data: bytes
    sample_rate: int
    channels: int
    sample_width: int


class AudioSource(Protocol):
    async def read_frame(self) -> AudioFrame: ...


class VADProvider(Protocol):
    async def capture_utterance(self, source: AudioSource) -> AudioSegment: ...


class STTProvider(Protocol):
    async def transcribe(self, audio: AudioSegment) -> str: ...


class AudioOutput(Protocol):
    async def play(self, audio: AudioClip) -> None: ...
