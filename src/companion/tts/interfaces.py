from typing import Protocol

from companion.audio.interfaces import AudioClip


class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> AudioClip: ...
