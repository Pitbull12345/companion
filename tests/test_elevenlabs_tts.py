import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from companion.audio.interfaces import AudioClip
from companion.application import (
    ApplicationConfig,
    CompositionFactories,
    LLMProviderRegistry,
    compose_character_runtime,
    create_default_tts_registry,
)
from companion.audio.interfaces import AudioFrame, AudioSegment
from companion.character import load_character
from companion.runtime.turn import TurnState
from companion.tts.elevenlabs import ElevenLabsTTSProvider, PCM_SAMPLE_RATES
from companion.tts.errors import TTSError
from companion.tts.interfaces import TTSProvider


class FakeResponse:
    def __init__(self, content: bytes = b"\0\0", *, status: int = 200) -> None:
        self.content = content
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://eleven.test/v1/text-to-speech/id")
            raise httpx.HTTPStatusError(
                "request failed",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


class FakeClient:
    def __init__(self, results: list[Any]) -> None:
        self._results = iter(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.close_calls = 0

    async def post(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((path, kwargs))
        result = next(self._results)
        if isinstance(result, BaseException):
            raise result
        return result

    async def aclose(self) -> None:
        self.close_calls += 1


def test_request_maps_voice_auth_text_model_and_format() -> None:
    async def exercise() -> None:
        client = FakeClient([FakeResponse(b"\x01\x00\x02\x00")])
        provider = ElevenLabsTTSProvider(
            "voice/with space",
            "test-key",
            model_id="test-model",
            output_format="pcm_22050",
            client=client,
        )

        clip = await provider.synthesize("Hello")

        assert clip == AudioClip(b"\x01\x00\x02\x00", 22_050, 1, 2)
        assert client.calls == [
            (
                "/v1/text-to-speech/voice%2Fwith%20space",
                {
                    "headers": {"xi-api-key": "test-key"},
                    "params": {"output_format": "pcm_22050"},
                    "json": {"text": "Hello", "model_id": "test-model"},
                },
            )
        ]

    asyncio.run(exercise())


@pytest.mark.parametrize(("output_format", "rate"), PCM_SAMPLE_RATES.items())
def test_supported_pcm_formats_map_to_exact_audio_metadata(
    output_format: str, rate: int
) -> None:
    async def exercise() -> None:
        provider = ElevenLabsTTSProvider(
            "voice",
            "key",
            output_format=output_format,
            client=FakeClient([FakeResponse(b"\0\0")]),
        )
        clip = await provider.synthesize("hello")
        assert clip.data == b"\0\0"
        assert (clip.sample_rate, clip.channels, clip.sample_width) == (rate, 1, 2)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "output_format", ["pcm_12345", "pcm_bad", "mp3_44100_128", "opus_48000_64", "ulaw_8000", "alaw_8000"]
)
def test_unsupported_or_encoded_formats_are_rejected(output_format: str) -> None:
    with pytest.raises(ValueError, match="unsupported ElevenLabs PCM"):
        ElevenLabsTTSProvider("voice", "key", output_format=output_format)


@pytest.mark.parametrize(
    ("text", "content", "message"),
    [
        ("  ", b"\0\0", "empty text"),
        ("hello", b"", "empty audio"),
        ("hello", b"\0", "malformed PCM"),
    ],
)
def test_empty_text_or_unusable_audio_is_rejected(
    text: str, content: bytes, message: str
) -> None:
    async def exercise() -> None:
        client = FakeClient([FakeResponse(content)])
        provider = ElevenLabsTTSProvider("voice", "key", client=client)
        with pytest.raises(TTSError, match=message):
            await provider.synthesize(text)
        if not text.strip():
            assert client.calls == []

    asyncio.run(exercise())


@pytest.mark.parametrize("status", [401, 403, 429, 400, 500, 503])
def test_http_status_is_translated_without_secret(status: int) -> None:
    async def exercise() -> None:
        provider = ElevenLabsTTSProvider(
            "voice", "never-print-this", client=FakeClient([FakeResponse(status=status)])
        )
        with pytest.raises(TTSError, match=f"HTTP {status}") as raised:
            await provider.synthesize("hello")
        assert "never-print-this" not in str(raised.value)
        assert "never-print-this" not in repr(provider)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (httpx.ReadTimeout("slow"), "timed out"),
        (httpx.ConnectError("offline"), "request failed"),
    ],
)
def test_network_failures_are_translated(failure: Exception, message: str) -> None:
    async def exercise() -> None:
        provider = ElevenLabsTTSProvider(
            "voice", "key", client=FakeClient([failure])
        )
        with pytest.raises(TTSError, match=message) as raised:
            await provider.synthesize("hello")
        assert raised.value.__cause__ is failure

    asyncio.run(exercise())


def test_cancellation_propagates() -> None:
    class BlockingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([])
            self.started = asyncio.Event()

        async def post(self, path: str, **kwargs: Any) -> FakeResponse:
            self.started.set()
            await asyncio.Event().wait()

    async def exercise() -> None:
        client = BlockingClient()
        provider = ElevenLabsTTSProvider("voice", "key", client=client)
        request = asyncio.create_task(provider.synthesize("hello"))
        await client.started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

    asyncio.run(exercise())


def test_owned_client_is_lazy_reused_and_closed_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options: list[dict[str, Any]] = []
    client = FakeClient([FakeResponse(), FakeResponse()])

    def create_client(**kwargs: Any) -> FakeClient:
        options.append(kwargs)
        return client

    monkeypatch.setattr("companion.tts.elevenlabs.httpx.AsyncClient", create_client)
    provider = ElevenLabsTTSProvider(
        "voice", "secret", base_url="https://eleven.test", timeout=12.5
    )
    assert options == []

    async def exercise() -> None:
        await provider.synthesize("one")
        await provider.synthesize("two")
        await provider.close()
        await provider.close()

    asyncio.run(exercise())
    assert options == [{"base_url": "https://eleven.test", "timeout": 12.5}]
    assert len(client.calls) == 2
    assert client.close_calls == 1


def test_close_before_use_is_safe_and_does_not_create_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creations = 0

    def create_client(**kwargs: Any) -> FakeClient:
        nonlocal creations
        creations += 1
        return FakeClient([])

    monkeypatch.setattr("companion.tts.elevenlabs.httpx.AsyncClient", create_client)
    provider = ElevenLabsTTSProvider("voice", "key")
    asyncio.run(provider.close())
    asyncio.run(provider.close())
    assert creations == 0


def test_falsey_injected_client_is_reused_not_closed_and_satisfies_contract() -> None:
    class FalseyClient(FakeClient):
        def __bool__(self) -> bool:
            return False

    async def consume(provider: TTSProvider) -> AudioClip:
        return await provider.synthesize("hello")

    async def exercise() -> None:
        client = FalseyClient([FakeResponse()])
        provider = ElevenLabsTTSProvider("voice", "key", client=client)
        assert await consume(provider) == AudioClip(b"\0\0", 24_000, 1, 2)
        await provider.close()
        assert client.close_calls == 0

    asyncio.run(exercise())


def test_two_turn_character_integration_reuses_client_and_generic_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = tmp_path / "character"
    package.mkdir()
    (package / "character.toml").write_text(
        """
id = "eleven"
name = "Eleven"
system_prompt = "Eleven personality."

[llm]
provider = "fake-llm"
model = "model"

[tts]
provider = "elevenlabs"
voice = "voice-id"
"""
    )
    client = FakeClient([FakeResponse(b"\x01\x00"), FakeResponse(b"\x02\x00")])
    monkeypatch.setattr(
        "companion.tts.elevenlabs.httpx.AsyncClient", lambda **options: client
    )

    class Source:
        def __init__(self) -> None:
            self.close_calls = 0

        async def read_frame(self):
            raise AssertionError("fake VAD does not read source")

        async def close(self):
            self.close_calls += 1

    class VAD:
        async def capture_utterance(self, source):
            return AudioSegment((AudioFrame(b"\0\0", 16_000, 1, 2),))

    class STT:
        def __init__(self) -> None:
            self.calls = 0

        async def transcribe(self, audio):
            self.calls += 1
            return f"question {self.calls}"

    class LLM:
        def __init__(self) -> None:
            self.contexts = []

        async def generate(self, messages):
            self.contexts.append(messages)
            return f"answer {len(self.contexts)}"

    class Output:
        def __init__(self) -> None:
            self.clips = []

        async def play(self, clip):
            self.clips.append(clip)

    source, stt, llm, output = Source(), STT(), LLM(), Output()
    llm_registry: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    llm_registry.register("fake-llm", lambda preference, config: llm)
    states = []
    completed = 0
    application = None

    def on_completed(result):
        nonlocal completed
        completed += 1
        if completed == 2:
            application.loop.request_stop()

    application = compose_character_runtime(
        load_character(package),
        ApplicationConfig("whisper", elevenlabs_api_key="test-key"),
        llm_registry=llm_registry,
        tts_registry=create_default_tts_registry(),
        factories=CompositionFactories(
            audio_source=lambda: source,
            vad=VAD,
            stt=lambda path: stt,
            audio_output=lambda: output,
        ),
        on_transition=states.append,
        on_turn_completed=on_completed,
    )
    asyncio.run(application.run())

    assert len(client.calls) == 2
    assert llm.contexts[1][-2].content == "answer 1"
    assert output.clips == [
        AudioClip(b"\x01\x00", 24_000, 1, 2),
        AudioClip(b"\x02\x00", 24_000, 1, 2),
    ]
    assert states == [
        TurnState.TRANSCRIBING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
        TurnState.TRANSCRIBING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
    ]
    assert client.close_calls == 1
    assert source.close_calls == 1
