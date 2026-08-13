from typing import Protocol


class TTSProvider(Protocol):
    async def speak(self, text: str) -> None: ...
