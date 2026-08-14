import asyncio
import threading
import wave
from collections.abc import Sequence

import pytest

from companion.audio.interfaces import AudioClip, AudioOutput
from companion.tts.errors import TTSError
from companion.tts.interfaces import TTSProvider
from companion.tts.piper import PiperTTSProvider, _load_local_voice


class FakeVoice:
    def __init__(self, results: Sequence[bytes | Exception]) -> None:
        self._results = iter(results)
        self.texts: list[str] = []
        self.threads: list[int] = []

    def synthesize_wav(self, text: str, wav_file: wave.Wave_write) -> None:
        self.texts.append(text)
        self.threads.append(threading.get_ident())
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        wav_file.setframerate(22_050)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.writeframes(result)


class FakeVoiceFactory:
    def __init__(self, voice: FakeVoice | Exception) -> None:
        self.voice = voice
        self.calls: list[tuple[str, str | None]] = []
        self.threads: list[int] = []

    def __call__(self, model_path: str, config_path: str | None) -> FakeVoice:
        self.calls.append((model_path, config_path))
        self.threads.append(threading.get_ident())
        if isinstance(self.voice, Exception):
            raise self.voice
        return self.voice


def test_default_loader_uses_configured_local_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []
    voice = FakeVoice([])

    class VoiceLoader:
        @staticmethod
        def load(model_path: str, *, config_path: str | None = None) -> FakeVoice:
            calls.append((model_path, config_path))
            return voice

    monkeypatch.setattr("piper.PiperVoice", VoiceLoader)

    assert _load_local_voice("/voices/local.onnx", "/voices/local.json") is voice
    assert calls == [("/voices/local.onnx", "/voices/local.json")]


def test_text_pcm_configuration_reuse_and_worker_boundary() -> None:
    async def exercise() -> None:
        event_loop_thread = threading.get_ident()
        voice = FakeVoice([b"\x01\x00\x02\x00", b"\x03\x00"])
        factory = FakeVoiceFactory(voice)
        provider = PiperTTSProvider(
            "/voices/amy.onnx",
            config_path="/voices/amy.onnx.json",
            voice_factory=factory,
        )

        assert await provider.synthesize("Hello") == AudioClip(
            b"\x01\x00\x02\x00", 22_050, 1, 2
        )
        assert await provider.synthesize("Again") == AudioClip(
            b"\x03\x00", 22_050, 1, 2
        )
        assert voice.texts == ["Hello", "Again"]
        assert factory.calls == [
            ("/voices/amy.onnx", "/voices/amy.onnx.json")
        ]
        assert factory.threads[0] != event_loop_thread
        assert all(thread != event_loop_thread for thread in voice.threads)

    asyncio.run(exercise())


def test_empty_text_fails_before_voice_loading() -> None:
    async def exercise() -> None:
        factory = FakeVoiceFactory(FakeVoice([]))
        provider = PiperTTSProvider("voice", voice_factory=factory)
        with pytest.raises(TTSError, match="empty text"):
            await provider.synthesize(" \n ")
        assert factory.calls == []

    asyncio.run(exercise())


def test_synthesis_failure_is_wrapped_and_provider_can_be_reused() -> None:
    async def exercise() -> None:
        failure = RuntimeError("synthesis broke")
        voice = FakeVoice([failure, b"\x01\x00"])
        provider = PiperTTSProvider(
            "voice", voice_factory=FakeVoiceFactory(voice)
        )

        with pytest.raises(TTSError, match="synthesis broke") as raised:
            await provider.synthesize("first")
        assert raised.value.__cause__ is failure
        assert await provider.synthesize("second") == AudioClip(
            b"\x01\x00", 22_050, 1, 2
        )

    asyncio.run(exercise())


def test_empty_synthesized_audio_fails_clearly() -> None:
    async def exercise() -> None:
        provider = PiperTTSProvider(
            "voice", voice_factory=FakeVoiceFactory(FakeVoice([b""]))
        )
        with pytest.raises(TTSError, match="empty or malformed audio"):
            await provider.synthesize("hello")

    asyncio.run(exercise())


def test_cancellation_waits_for_synthesis_cleanup_and_propagates() -> None:
    class BlockingVoice(FakeVoice):
        def __init__(self) -> None:
            super().__init__([b"\x01\x00", b"\x02\x00"])
            self.started = threading.Event()
            self.release = threading.Event()

        def synthesize_wav(self, text: str, wav_file: wave.Wave_write) -> None:
            self.started.set()
            assert self.release.wait(timeout=1)
            super().synthesize_wav(text, wav_file)

    async def exercise() -> None:
        voice = BlockingVoice()
        provider = PiperTTSProvider(
            "voice", voice_factory=FakeVoiceFactory(voice)
        )
        request = asyncio.create_task(provider.synthesize("cancel me"))
        assert await asyncio.to_thread(voice.started.wait, 0.5)
        request.cancel()
        asyncio.get_running_loop().call_later(0.01, voice.release.set)
        with pytest.raises(asyncio.CancelledError):
            await request

        assert await provider.synthesize("reuse") == AudioClip(
            b"\x02\x00", 22_050, 1, 2
        )

    asyncio.run(exercise())


def test_tts_contract_and_fake_output_integration() -> None:
    class FakeOutput:
        def __init__(self) -> None:
            self.audio: list[AudioClip] = []

        async def play(self, audio: AudioClip) -> None:
            self.audio.append(audio)

    async def synthesize_and_play(
        tts: TTSProvider, output: AudioOutput, text: str
    ) -> AudioClip:
        clip = await tts.synthesize(text)
        await output.play(clip)
        return clip

    async def exercise() -> None:
        provider = PiperTTSProvider(
            "voice", voice_factory=FakeVoiceFactory(FakeVoice([b"\x01\x00"]))
        )
        output = FakeOutput()
        clip = await synthesize_and_play(provider, output, "integration")
        assert output.audio == [clip]

    asyncio.run(exercise())
