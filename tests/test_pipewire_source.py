import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from companion.audio.errors import AudioError
from companion.audio.interfaces import AudioFrame, AudioSource
from companion.audio.pipewire_source import PipeWireAudioSource


class FakeStdout:
    def __init__(self, results: Sequence[bytes | Exception]) -> None:
        self._results = iter(results)
        self.read_sizes: list[int] = []

    async def readexactly(self, n: int) -> bytes:
        self.read_sizes.append(n)
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        return result


class FakeProcess:
    def __init__(self, stdout: FakeStdout | None) -> None:
        self.stdout = stdout
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.communicate_calls = 0
        self.wait_calls = 0
        self.terminate_error: Exception | None = None
        self.wait_error: Exception | None = None

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_error is not None:
            raise self.terminate_error
        self.returncode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    async def communicate(self) -> tuple[bytes, bytes]:
        self.communicate_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return b"drained audio", b""

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.wait_error is not None:
            raise self.wait_error
        if self.returncode is None:
            self.returncode = 0
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


def pcm_frame_bytes(value: int) -> bytes:
    return value.to_bytes(2, "little", signed=True) * 320


def test_lazy_start_command_default_routing_frame_metadata_and_contract() -> None:
    async def consume(source: AudioSource) -> AudioFrame:
        return await source.read_frame()

    async def exercise() -> None:
        pcm = pcm_frame_bytes(1)
        stdout = FakeStdout([pcm])
        process = FakeProcess(stdout)
        factory = FakeProcessFactory(process)
        source = PipeWireAudioSource(process_factory=factory)

        assert factory.calls == []
        frame = await consume(source)

        assert frame == AudioFrame(pcm, sample_rate=16_000, channels=1, sample_width=2)
        command, options = factory.calls[0]
        assert command == (
            "pw-cat",
            "--record",
            "--raw",
            "--rate",
            "16000",
            "--channels",
            "1",
            "--format",
            "s16",
            "-",
        )
        assert "--target" not in command
        assert options == {
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.DEVNULL,
            "limit": 640,
        }
        assert stdout.read_sizes == [640]
        await source.close()

    asyncio.run(exercise())


def test_repeated_reads_preserve_order_and_reuse_process() -> None:
    async def exercise() -> None:
        first = pcm_frame_bytes(1)
        second = pcm_frame_bytes(2)
        stdout = FakeStdout([first, second])
        factory = FakeProcessFactory(FakeProcess(stdout))
        source = PipeWireAudioSource(process_factory=factory)

        assert (await source.read_frame()).data == first
        assert (await source.read_frame()).data == second
        assert len(factory.calls) == 1
        assert stdout.read_sizes == [640, 640]
        await source.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("pw-cat"), "unavailable"),
        (RuntimeError("spawn failed"), "could not start"),
    ],
)
def test_startup_failures_are_wrapped_and_remain_fatal(
    failure: Exception, message: str
) -> None:
    async def exercise() -> None:
        factory = FakeProcessFactory(failure)
        source = PipeWireAudioSource(process_factory=factory)

        for _ in range(2):
            with pytest.raises(AudioError, match=message) as raised:
                await source.read_frame()
            assert raised.value.__cause__ is failure
        assert len(factory.calls) == 1
        await source.close()

    asyncio.run(exercise())


def test_unavailable_stdout_terminates_and_waits() -> None:
    async def exercise() -> None:
        process = FakeProcess(None)
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process)
        )

        with pytest.raises(AudioError, match="stdout is unavailable"):
            await source.read_frame()
        assert process.terminate_calls == 1
        assert process.communicate_calls == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("read_failure", "message"),
    [
        (asyncio.IncompleteReadError(b"", 640), "exited unexpectedly"),
        (asyncio.IncompleteReadError(b"\x00\x00", 640), "incomplete PCM frame"),
        (RuntimeError("read broke"), "read failed: read broke"),
    ],
)
def test_fatal_read_failures_cleanup_and_do_not_hang_later_reads(
    read_failure: Exception, message: str
) -> None:
    async def exercise() -> None:
        process = FakeProcess(FakeStdout([read_failure]))
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process)
        )

        for _ in range(2):
            with pytest.raises(AudioError, match=message):
                await asyncio.wait_for(source.read_frame(), 0.1)
        assert process.terminate_calls == 1
        assert process.communicate_calls == 1

    asyncio.run(exercise())


def test_malformed_frame_length_is_fatal_and_cleaned_up() -> None:
    async def exercise() -> None:
        process = FakeProcess(FakeStdout([b"\x00\x00"]))
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process)
        )

        with pytest.raises(AudioError, match="malformed PCM"):
            await source.read_frame()
        assert process.terminate_calls == 1
        assert process.communicate_calls == 1

    asyncio.run(exercise())


def test_cancelled_read_terminates_waits_and_propagates() -> None:
    class BlockingStdout(FakeStdout):
        def __init__(self) -> None:
            super().__init__([])
            self.started = asyncio.Event()

        async def readexactly(self, n: int) -> bytes:
            self.read_sizes.append(n)
            self.started.set()
            await asyncio.Event().wait()

    async def exercise() -> None:
        stdout = BlockingStdout()
        process = FakeProcess(stdout)
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process)
        )
        request = asyncio.create_task(source.read_frame())
        await stdout.started.wait()
        request.cancel()

        with pytest.raises(asyncio.CancelledError):
            await request

        assert process.terminate_calls == 1
        assert process.communicate_calls == 1
        with pytest.raises(AudioError, match="closed PipeWire audio source"):
            await source.read_frame()

    asyncio.run(exercise())


def test_close_is_idempotent_and_terminates_then_waits() -> None:
    async def exercise() -> None:
        process = FakeProcess(FakeStdout([]))
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process)
        )
        await source.start()

        await source.close()
        await source.close()

        assert process.terminate_calls == 1
        assert process.kill_calls == 0
        assert process.communicate_calls == 1
        with pytest.raises(AudioError, match="closed PipeWire audio source"):
            await source.read_frame()

    asyncio.run(exercise())


def test_process_ignoring_terminate_is_killed_and_reaped_after_timeout() -> None:
    class IgnoreTerminateProcess(FakeProcess):
        def __init__(self) -> None:
            super().__init__(FakeStdout([]))
            self.killed = asyncio.Event()

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            super().kill()
            self.killed.set()

        async def communicate(self) -> tuple[bytes, bytes]:
            self.communicate_calls += 1
            if self.returncode is None:
                await self.killed.wait()
            assert self.returncode is not None
            return b"drained after kill", b""

    async def exercise() -> None:
        process = IgnoreTerminateProcess()
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process),
            shutdown_timeout=0.01,
        )
        await source.start()

        await asyncio.wait_for(source.close(), timeout=0.2)

        assert process.terminate_calls == 1
        assert process.kill_calls == 1
        assert process.communicate_calls == 1

    asyncio.run(exercise())


def test_cleanup_cannot_hang_if_process_ignores_kill() -> None:
    class UnstoppableProcess(FakeProcess):
        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

        async def communicate(self) -> tuple[bytes, bytes]:
            self.communicate_calls += 1
            await asyncio.Event().wait()

    async def exercise() -> None:
        process = UnstoppableProcess(FakeStdout([]))
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process),
            shutdown_timeout=0.01,
        )
        await source.start()

        with pytest.raises(AudioError, match="could not be reaped after kill"):
            await asyncio.wait_for(source.close(), timeout=0.2)

        assert process.terminate_calls == 1
        assert process.kill_calls == 1
        assert process.communicate_calls == 1

    asyncio.run(exercise())


def test_close_failure_is_provider_neutral_and_still_waits() -> None:
    async def exercise() -> None:
        process = FakeProcess(FakeStdout([]))
        process.terminate_error = RuntimeError("terminate failed")
        source = PipeWireAudioSource(
            process_factory=FakeProcessFactory(process)
        )
        await source.start()

        with pytest.raises(AudioError, match="terminate failed") as raised:
            await source.close()
        assert isinstance(raised.value.__cause__, RuntimeError)
        assert process.communicate_calls == 1

    asyncio.run(exercise())
