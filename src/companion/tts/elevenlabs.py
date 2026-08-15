import asyncio
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from companion.audio.interfaces import AudioClip
from companion.tts.errors import TTSError


PCM_SAMPLE_RATES: Mapping[str, int] = {
    "pcm_16000": 16_000,
    "pcm_22050": 22_050,
    "pcm_24000": 24_000,
    "pcm_44100": 44_100,
}


class ElevenLabsResponse(Protocol):
    status_code: int
    content: bytes

    def raise_for_status(self) -> None: ...


class ElevenLabsClient(Protocol):
    async def post(self, path: str, **kwargs: Any) -> ElevenLabsResponse: ...

    async def aclose(self) -> None: ...


class ElevenLabsTTSProvider:
    """Non-streaming ElevenLabs adapter returning decoded raw PCM."""

    def __init__(
        self,
        voice_id: str,
        api_key: str,
        *,
        model_id: str = "eleven_multilingual_v2",
        base_url: str = "https://api.elevenlabs.io",
        timeout: float = 30.0,
        output_format: str = "pcm_24000",
        client: ElevenLabsClient | None = None,
    ) -> None:
        if output_format not in PCM_SAMPLE_RATES:
            raise ValueError(f"unsupported ElevenLabs PCM output format {output_format!r}")
        self._voice_id = voice_id
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = base_url
        self._timeout = timeout
        self._output_format = output_format
        self._sample_rate = PCM_SAMPLE_RATES[output_format]
        self._client = client
        self._owns_client = client is None
        self._closed = False
        self._client_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()

    async def _get_client(self) -> ElevenLabsClient:
        async with self._client_lock:
            if self._closed:
                raise TTSError("ElevenLabs provider is closed")
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self._base_url, timeout=self._timeout
                )
            return self._client

    async def synthesize(self, text: str) -> AudioClip:
        if not text.strip():
            raise TTSError("cannot synthesize empty text")
        try:
            client = await self._get_client()
            response = await client.post(
                f"/v1/text-to-speech/{quote(self._voice_id, safe='')}",
                headers={"xi-api-key": self._api_key},
                params={"output_format": self._output_format},
                json={"text": text, "model_id": self._model_id},
            )
            response.raise_for_status()
            audio = response.content
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            raise TTSError("ElevenLabs request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise TTSError(
                f"ElevenLabs request failed with HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise TTSError("ElevenLabs request failed") from exc

        if not audio:
            raise TTSError("ElevenLabs returned empty audio")
        if len(audio) % 2:
            raise TTSError("ElevenLabs returned malformed PCM audio")
        return AudioClip(
            data=audio,
            sample_rate=self._sample_rate,
            channels=1,
            sample_width=2,
        )

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self._owns_client and self._client is not None:
                await self._client.aclose()
