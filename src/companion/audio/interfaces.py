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


class AudioSource(Protocol):
    async def read_frame(self) -> AudioFrame: ...


class VADProvider(Protocol):
    async def capture_utterance(self, source: AudioSource) -> AudioSegment: ...


class STTProvider(Protocol):
    async def transcribe(self, audio: AudioSegment) -> str: ...
