import asyncio
import threading
from typing import Any

import pytest

from companion.audio.errors import PlaybackError
from companion.audio.interfaces import AudioClip, AudioOutput
from companion.audio.sounddevice_output import SoundDeviceAudioOutput


class FakeOutputStream:
    def __init__(self, **options: Any) -> None:
        self.options = options
        self.data: list[bytes] = []
        self.events: list[str] = []
        self.threads: list[int] = []

    def start(self) -> None:
        self.events.append("start")

    def write(self, data: bytes) -> None:
        self.threads.append(threading.get_ident())
        self.data.append(data)

    def stop(self) -> None:
        self.events.append("stop")

    def close(self) -> None:
        self.events.append("close")


def test_output_contract_configuration_pcm_and_worker_boundary() -> None:
    async def consume(output: AudioOutput, audio: AudioClip) -> None:
        await output.play(audio)

    async def exercise() -> None:
        event_loop_thread = threading.get_ident()
        streams: list[FakeOutputStream] = []

        def factory(**options: Any) -> FakeOutputStream:
            stream = FakeOutputStream(**options)
            streams.append(stream)
            return stream

        output = SoundDeviceAudioOutput(device="speaker", stream_factory=factory)
        clip = AudioClip(b"\x01\x00\x02\x00", 24_000, 1, 2)
        await consume(output, clip)

        assert len(streams) == 1
        assert streams[0].options == {
            "samplerate": 24_000,
            "channels": 1,
            "dtype": "int16",
            "device": "speaker",
        }
        assert streams[0].data == [clip.data]
        assert streams[0].events == ["start", "stop", "close"]
        assert streams[0].threads[0] != event_loop_thread

    asyncio.run(exercise())


def test_supported_native_rate_does_not_resample() -> None:
    async def exercise() -> None:
        checks: list[dict[str, Any]] = []
        resampler_calls = 0
        streams: list[FakeOutputStream] = []

        def check_settings(**options: Any) -> None:
            checks.append(options)

        def resample(audio: AudioClip, target_rate: int) -> AudioClip:
            nonlocal resampler_calls
            resampler_calls += 1
            return audio

        def factory(**options: Any) -> FakeOutputStream:
            stream = FakeOutputStream(**options)
            streams.append(stream)
            return stream

        output = SoundDeviceAudioOutput(
            device="speaker",
            stream_factory=factory,
            output_settings_checker=check_settings,
            device_query=lambda **options: pytest.fail("device query was unnecessary"),
            resampler=resample,
        )
        clip = AudioClip(b"\x01\x00", 22_050, 1, 2)
        await output.play(clip)

        assert checks == [
            {
                "device": "speaker",
                "samplerate": 22_050,
                "channels": 1,
                "dtype": "int16",
            }
        ]
        assert resampler_calls == 0
        assert streams[0].options["samplerate"] == 22_050
        assert streams[0].data == [clip.data]

    asyncio.run(exercise())


def test_unsupported_native_rate_resamples_to_device_default() -> None:
    async def exercise() -> None:
        event_loop_thread = threading.get_ident()
        queries: list[dict[str, Any]] = []
        resampler_calls: list[tuple[AudioClip, int, int]] = []
        streams: list[FakeOutputStream] = []
        source = AudioClip(b"\x01\x00\x02\x00", 22_050, 1, 2)
        adapted = AudioClip(b"\x01\x00\x01\x00\x02\x00\x02\x00", 44_100, 1, 2)

        def reject_native(**options: Any) -> None:
            raise RuntimeError("PaInvalidSampleRate")

        def query_device(**options: Any) -> dict[str, float]:
            queries.append(options)
            return {"default_samplerate": 44_100.0}

        def resample(audio: AudioClip, target_rate: int) -> AudioClip:
            resampler_calls.append((audio, target_rate, threading.get_ident()))
            return adapted

        def factory(**options: Any) -> FakeOutputStream:
            stream = FakeOutputStream(**options)
            streams.append(stream)
            return stream

        output = SoundDeviceAudioOutput(
            device=3,
            stream_factory=factory,
            output_settings_checker=reject_native,
            device_query=query_device,
            resampler=resample,
        )
        await output.play(source)

        assert queries == [{"device": 3, "kind": "output"}]
        assert resampler_calls[0][:2] == (source, 44_100)
        assert resampler_calls[0][2] != event_loop_thread
        assert streams[0].options["samplerate"] == 44_100
        assert streams[0].options["channels"] == source.channels
        assert streams[0].data == [adapted.data]

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("resampler_result", "message"),
    [
        (RuntimeError("soxr broke"), "soxr broke"),
        (AudioClip(b"\x00", 44_100, 1, 2), "frame-aligned"),
        (AudioClip(b"\x00\x00", 44_100, 2, 2), "incompatible PCM metadata"),
    ],
)
def test_resampling_failure_or_malformed_result_fails_before_device_use(
    resampler_result: AudioClip | Exception, message: str
) -> None:
    async def exercise() -> None:
        stream_calls = 0

        def factory(**options: Any) -> FakeOutputStream:
            nonlocal stream_calls
            stream_calls += 1
            return FakeOutputStream(**options)

        def resample(audio: AudioClip, target_rate: int) -> AudioClip:
            if isinstance(resampler_result, Exception):
                raise resampler_result
            return resampler_result

        output = SoundDeviceAudioOutput(
            stream_factory=factory,
            output_settings_checker=lambda **options: (_ for _ in ()).throw(
                RuntimeError("unsupported")
            ),
            device_query=lambda **options: {"default_samplerate": 44_100},
            resampler=resample,
        )
        with pytest.raises(PlaybackError, match=message):
            await output.play(AudioClip(b"\x01\x00", 22_050, 1, 2))
        assert stream_calls == 0

    asyncio.run(exercise())


def test_playback_failure_is_wrapped_and_stream_is_closed() -> None:
    class FailingStream(FakeOutputStream):
        def write(self, data: bytes) -> None:
            raise RuntimeError("device vanished")

    async def exercise() -> None:
        stream = FailingStream()
        output = SoundDeviceAudioOutput(stream_factory=lambda **options: stream)
        with pytest.raises(PlaybackError, match="device vanished") as raised:
            await output.play(AudioClip(b"\x01\x00", 16_000, 1, 2))
        assert isinstance(raised.value.__cause__, RuntimeError)
        assert stream.events == ["start", "close"]

    asyncio.run(exercise())


def test_close_failure_does_not_mask_playback_failure() -> None:
    playback_failure = RuntimeError("write failed")
    close_failure = RuntimeError("close failed")

    class DoublyFailingStream(FakeOutputStream):
        def write(self, data: bytes) -> None:
            raise playback_failure

        def close(self) -> None:
            self.events.append("close")
            raise close_failure

    async def exercise() -> None:
        stream = DoublyFailingStream()
        output = SoundDeviceAudioOutput(stream_factory=lambda **options: stream)

        with pytest.raises(PlaybackError, match="write failed") as raised:
            await output.play(AudioClip(b"\x01\x00", 16_000, 1, 2))

        assert raised.value.__cause__ is playback_failure
        assert "close failed" not in str(raised.value)
        assert stream.events == ["start", "close"]

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("audio", "message"),
    [
        (AudioClip(b"", 16_000, 1, 2), "empty audio"),
        (AudioClip(b"\x00", 16_000, 1, 2), "frame-aligned"),
        (AudioClip(b"\x00", 16_000, 1, 3), "sample width"),
    ],
)
def test_invalid_audio_fails_before_device_use(
    audio: AudioClip, message: str
) -> None:
    async def exercise() -> None:
        calls = 0

        def factory(**options: Any) -> FakeOutputStream:
            nonlocal calls
            calls += 1
            return FakeOutputStream(**options)

        output = SoundDeviceAudioOutput(stream_factory=factory)
        with pytest.raises(PlaybackError, match=message):
            await output.play(audio)
        assert calls == 0

    asyncio.run(exercise())


def test_cancellation_waits_for_device_cleanup_and_propagates() -> None:
    class BlockingStream(FakeOutputStream):
        def __init__(self) -> None:
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def write(self, data: bytes) -> None:
            self.started.set()
            assert self.release.wait(timeout=1)
            super().write(data)

    async def exercise() -> None:
        stream = BlockingStream()
        output = SoundDeviceAudioOutput(stream_factory=lambda **options: stream)
        request = asyncio.create_task(
            output.play(AudioClip(b"\x01\x00", 16_000, 1, 2))
        )
        assert await asyncio.to_thread(stream.started.wait, 0.5)
        request.cancel()
        asyncio.get_running_loop().call_later(0.01, stream.release.set)
        with pytest.raises(asyncio.CancelledError):
            await request
        assert stream.events == ["start", "stop", "close"]

    asyncio.run(exercise())
