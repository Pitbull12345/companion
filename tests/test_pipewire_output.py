import asyncio
from typing import Any

import pytest

from companion.audio.errors import PlaybackError
from companion.audio.interfaces import AudioClip, AudioOutput
from companion.audio.pipewire_output import PipeWireAudioOutput


class FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stderr: bytes = b"",
        communicate_error: Exception | None = None,
    ) -> None:
        self.returncode: int | None = None
        self._final_returncode = returncode
        self._stderr = stderr
        self._communicate_error = communicate_error
        self.inputs: list[bytes | None] = []
        self.terminate_calls = 0
        self.wait_calls = 0

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.inputs.append(input)
        if self._communicate_error is not None:
            raise self._communicate_error
        self.returncode = self._final_returncode
        return b"", self._stderr

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = -15

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = self._final_returncode
        return self.returncode


class FakeProcessFactory:
    def __init__(self, result: FakeProcess | Exception) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def __call__(self, *command: str, **options: Any) -> FakeProcess:
        self.calls.append((command, options))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("sample_width", "pipewire_format"),
    [(1, "s8"), (2, "s16"), (4, "s32")],
)
def test_raw_pcm_metadata_format_and_default_routing(
    sample_width: int, pipewire_format: str
) -> None:
    async def consume(output: AudioOutput, audio: AudioClip) -> None:
        await output.play(audio)

    async def exercise() -> None:
        process = FakeProcess()
        factory = FakeProcessFactory(process)
        output = PipeWireAudioOutput(process_factory=factory)
        pcm = b"\x01" * (2 * sample_width)

        await consume(output, AudioClip(pcm, 22_050, 2, sample_width))

        command, options = factory.calls[0]
        assert command == (
            "pw-cat",
            "--playback",
            "--raw",
            "--rate",
            "22050",
            "--channels",
            "2",
            "--format",
            pipewire_format,
            "-",
        )
        assert "--target" not in command
        assert options == {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.DEVNULL,
            "stderr": asyncio.subprocess.PIPE,
        }
        assert process.inputs == [pcm]

    asyncio.run(exercise())


def test_nonzero_exit_becomes_playback_error() -> None:
    async def exercise() -> None:
        process = FakeProcess(returncode=7, stderr=b"sink unavailable\n")
        output = PipeWireAudioOutput(
            process_factory=FakeProcessFactory(process)
        )

        with pytest.raises(
            PlaybackError, match="status 7: sink unavailable"
        ):
            await output.play(AudioClip(b"\x01\x00", 22_050, 1, 2))

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("factory_failure", "message"),
    [
        (FileNotFoundError("pw-cat"), "unavailable"),
        (RuntimeError("spawn failed"), "could not start"),
    ],
)
def test_process_startup_failures_are_wrapped(
    factory_failure: Exception, message: str
) -> None:
    async def exercise() -> None:
        output = PipeWireAudioOutput(
            process_factory=FakeProcessFactory(factory_failure)
        )
        with pytest.raises(PlaybackError, match=message) as raised:
            await output.play(AudioClip(b"\x01\x00", 22_050, 1, 2))
        assert raised.value.__cause__ is factory_failure

    asyncio.run(exercise())


def test_broken_stdin_terminates_process_and_is_wrapped() -> None:
    async def exercise() -> None:
        failure = BrokenPipeError("stdin closed")
        process = FakeProcess(communicate_error=failure)
        output = PipeWireAudioOutput(
            process_factory=FakeProcessFactory(process)
        )

        with pytest.raises(PlaybackError, match="stdin closed") as raised:
            await output.play(AudioClip(b"\x01\x00", 22_050, 1, 2))

        assert raised.value.__cause__ is failure
        assert process.terminate_calls == 1
        assert process.wait_calls == 1

    asyncio.run(exercise())


def test_cancellation_terminates_waits_and_propagates() -> None:
    class BlockingProcess(FakeProcess):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def communicate(
            self, input: bytes | None = None
        ) -> tuple[bytes, bytes]:
            self.inputs.append(input)
            self.started.set()
            await asyncio.Event().wait()

    async def exercise() -> None:
        process = BlockingProcess()
        output = PipeWireAudioOutput(
            process_factory=FakeProcessFactory(process)
        )
        request = asyncio.create_task(
            output.play(AudioClip(b"\x01\x00", 22_050, 1, 2))
        )
        await process.started.wait()
        request.cancel()

        with pytest.raises(asyncio.CancelledError):
            await request

        assert process.terminate_calls == 1
        assert process.wait_calls == 1
        assert process.returncode == -15

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("audio", "message"),
    [
        (AudioClip(b"", 22_050, 1, 2), "empty audio"),
        (AudioClip(b"\x00", 22_050, 1, 2), "frame-aligned"),
        (AudioClip(b"\x00\x00\x00", 22_050, 1, 3), "sample width"),
    ],
)
def test_invalid_pcm_fails_before_process_creation(
    audio: AudioClip, message: str
) -> None:
    async def exercise() -> None:
        factory = FakeProcessFactory(FakeProcess())
        output = PipeWireAudioOutput(process_factory=factory)
        with pytest.raises(PlaybackError, match=message):
            await output.play(audio)
        assert factory.calls == []

    asyncio.run(exercise())
