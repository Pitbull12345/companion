import asyncio
from typing import Any

import pytest

from companion.audio.errors import AudioError
from companion.audio.interfaces import AudioFrame, AudioSource
from companion.audio.sounddevice_source import SoundDeviceAudioSource


class FakeStream:
    def __init__(self, **options: Any) -> None:
        self.options = options
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def emit(self, data: bytes, status: Any = None) -> None:
        self.options["callback"](data, len(data) // 2, None, status)


class FakeBackend:
    def __init__(self) -> None:
        self.stream: FakeStream | None = None

    def input_stream(self, **options: Any) -> FakeStream:
        self.stream = FakeStream(**options)
        return self.stream


def test_produces_audio_frame_with_requested_metadata() -> None:
    async def exercise() -> None:
        backend = FakeBackend()
        source = SoundDeviceAudioSource(
            sample_rate=22_050,
            channels=2,
            stream_factory=backend.input_stream,
        )
        await source.start()
        assert backend.stream is not None

        pcm = b"\x01\x02\x03\x04"
        backend.stream.emit(pcm)
        frame = await source.read_frame()

        assert frame == AudioFrame(pcm, sample_rate=22_050, channels=2, sample_width=2)
        source.close()

    asyncio.run(exercise())


def test_configures_and_cleans_up_input_stream() -> None:
    async def exercise() -> None:
        backend = FakeBackend()
        source = SoundDeviceAudioSource(stream_factory=backend.input_stream)
        await source.start()
        assert backend.stream is not None

        assert backend.stream.options["samplerate"] == 16_000
        assert backend.stream.options["channels"] == 1
        assert backend.stream.options["dtype"] == "int16"
        assert backend.stream.started

        source.close()
        source.close()
        assert backend.stream.stopped
        assert backend.stream.closed

    asyncio.run(exercise())


def test_initialization_failure_is_wrapped() -> None:
    async def exercise() -> None:
        def fail(**options: Any) -> FakeStream:
            del options
            raise OSError("no input device")

        with pytest.raises(AudioError, match="could not open microphone.*no input device"):
            await SoundDeviceAudioSource(stream_factory=fail).start()

    asyncio.run(exercise())


def test_close_wakes_pending_read_and_rejects_future_reads() -> None:
    async def exercise() -> None:
        backend = FakeBackend()
        source = SoundDeviceAudioSource(stream_factory=backend.input_stream)
        pending = asyncio.create_task(source.read_frame())
        await asyncio.sleep(0)

        source.close()

        with pytest.raises(AudioError, match="closed while waiting"):
            await pending
        with pytest.raises(AudioError, match="closed audio source"):
            await source.read_frame()

    asyncio.run(exercise())


def test_callback_failure_is_reported() -> None:
    async def exercise() -> None:
        backend = FakeBackend()
        source = SoundDeviceAudioSource(stream_factory=backend.input_stream)
        await source.start()
        assert backend.stream is not None
        backend.stream.emit(b"", status="input overflow")

        with pytest.raises(AudioError, match="input overflow"):
            await source.read_frame()
        with pytest.raises(AudioError, match="input overflow"):
            await asyncio.wait_for(source.read_frame(), timeout=0.1)
        source.close()

    asyncio.run(exercise())


def test_satisfies_audio_source_contract() -> None:
    async def consume(source: AudioSource) -> AudioFrame:
        return await source.read_frame()

    async def exercise() -> None:
        backend = FakeBackend()
        source = SoundDeviceAudioSource(stream_factory=backend.input_stream)
        await source.start()
        assert backend.stream is not None
        backend.stream.emit(b"\x00\x00")
        assert (await consume(source)).data == b"\x00\x00"
        source.close()

    asyncio.run(exercise())


def test_can_be_constructed_without_a_running_event_loop() -> None:
    backend = FakeBackend()
    source = SoundDeviceAudioSource(stream_factory=backend.input_stream)

    assert backend.stream is None

    async def exercise() -> None:
        pending = asyncio.create_task(source.read_frame())
        await asyncio.sleep(0)
        assert backend.stream is not None
        backend.stream.emit(b"\x05\x06")
        assert (await pending).data == b"\x05\x06"
        source.close()

    asyncio.run(exercise())


def test_buffer_is_bounded_and_drops_oldest_stale_frames() -> None:
    async def exercise() -> None:
        backend = FakeBackend()
        source = SoundDeviceAudioSource(
            max_buffered_frames=2,
            stream_factory=backend.input_stream,
        )
        await source.start()
        assert backend.stream is not None

        backend.stream.emit(b"\x01\x00")
        backend.stream.emit(b"\x02\x00")
        backend.stream.emit(b"\x03\x00")

        assert (await source.read_frame()).data == b"\x02\x00"
        assert (await source.read_frame()).data == b"\x03\x00"
        source.close()

    asyncio.run(exercise())
