import asyncio
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest

from companion.audio.errors import STTError
from companion.audio.faster_whisper_stt import (
    FasterWhisperSTTProvider,
    _load_local_model,
)
from companion.audio.interfaces import AudioFrame, AudioSegment, STTProvider


def pcm_frame(samples: Sequence[int], **metadata: int) -> AudioFrame:
    return AudioFrame(
        b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples),
        **metadata,
    )


@dataclass
class FakeSegment:
    text: str


class FakeModel:
    def __init__(self, results: Sequence[Sequence[str] | Exception]) -> None:
        self.results = iter(results)
        self.audio: list[Any] = []
        self.vad_filters: list[bool] = []
        self.worker_threads: list[int] = []
        self.iterator_threads: list[int] = []

    def transcribe(self, audio: Any, *, vad_filter: bool) -> tuple[Any, None]:
        self.audio.append(audio.copy())
        self.vad_filters.append(vad_filter)
        self.worker_threads.append(threading.get_ident())
        result = next(self.results)
        if isinstance(result, Exception):
            raise result

        def segments() -> Any:
            self.iterator_threads.append(threading.get_ident())
            for text in result:
                yield FakeSegment(text)

        return segments(), None


class FakeFactory:
    def __init__(self, model: FakeModel | Exception) -> None:
        self.model = model
        self.calls: list[tuple[str, str, str]] = []
        self.threads: list[int] = []

    def __call__(self, path: str, device: str, compute_type: str) -> FakeModel:
        self.calls.append((path, device, compute_type))
        self.threads.append(threading.get_ident())
        if isinstance(self.model, Exception):
            raise self.model
        return self.model


def test_pcm_conversion_order_text_join_model_reuse_and_worker_boundary() -> None:
    async def exercise() -> None:
        event_loop_thread = threading.get_ident()
        model = FakeModel([["  hello ", " world\nagain "], [" second "]])
        factory = FakeFactory(model)
        provider = FasterWhisperSTTProvider(
            "/models/tiny",
            device="cpu",
            compute_type="int8",
            model_factory=factory,
        )

        first = await provider.transcribe(
            AudioSegment((pcm_frame([-32768, 0]), pcm_frame([16384, 32767])))
        )
        second = await provider.transcribe(AudioSegment((pcm_frame([1]),)))

        assert first == "hello world again"
        assert second == "second"
        assert factory.calls == [("/models/tiny", "cpu", "int8")]
        assert model.audio[0].tolist() == pytest.approx(
            [-1.0, 0.0, 0.5, 32767 / 32768]
        )
        assert model.vad_filters == [False, False]
        assert factory.threads[0] != event_loop_thread
        assert model.worker_threads == model.iterator_threads
        assert all(thread_id != event_loop_thread for thread_id in model.iterator_threads)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("bad_frame", "message"),
    [
        (pcm_frame([1], sample_rate=8_000), "sample rate"),
        (pcm_frame([1], channels=2), "channel count"),
        (pcm_frame([1], sample_width=1), "sample width"),
        (AudioFrame(b"\x00"), "sample-aligned"),
    ],
)
def test_invalid_audio_fails_before_model_use(
    bad_frame: AudioFrame, message: str
) -> None:
    async def exercise() -> None:
        factory = FakeFactory(FakeModel([["unused"]]))
        provider = FasterWhisperSTTProvider("model", model_factory=factory)
        with pytest.raises(STTError, match=message):
            await provider.transcribe(AudioSegment((bad_frame,)))
        assert factory.calls == []

    asyncio.run(exercise())


def test_empty_segment_fails_clearly() -> None:
    async def exercise() -> None:
        factory = FakeFactory(FakeModel([]))
        provider = FasterWhisperSTTProvider("model", model_factory=factory)

        for audio in (AudioSegment(()), AudioSegment((pcm_frame([]), pcm_frame([])))):
            with pytest.raises(STTError, match="empty audio segment"):
                await provider.transcribe(audio)

        assert factory.calls == []

    asyncio.run(exercise())


def test_concurrent_transcriptions_never_enter_owned_model_concurrently() -> None:
    class SerializedModel(FakeModel):
        def __init__(self) -> None:
            super().__init__([["first"], ["second"]])
            self.first_entered = threading.Event()
            self.release_first = threading.Event()
            self.call_count = 0
            self.active_calls = 0
            self.maximum_active_calls = 0
            self.state_lock = threading.Lock()

        def transcribe(self, audio: Any, *, vad_filter: bool) -> tuple[Any, None]:
            with self.state_lock:
                self.call_count += 1
                call_number = self.call_count
                self.active_calls += 1
                self.maximum_active_calls = max(
                    self.maximum_active_calls, self.active_calls
                )
            try:
                if call_number == 1:
                    self.first_entered.set()
                    assert self.release_first.wait(timeout=1)
                return super().transcribe(audio, vad_filter=vad_filter)
            finally:
                with self.state_lock:
                    self.active_calls -= 1

    async def exercise() -> None:
        model = SerializedModel()
        provider = FasterWhisperSTTProvider(
            "model", model_factory=FakeFactory(model)
        )
        audio = AudioSegment((pcm_frame([1]),))

        first = asyncio.create_task(provider.transcribe(audio))
        assert await asyncio.to_thread(model.first_entered.wait, 0.5)

        second_submitted = asyncio.Event()

        async def transcribe_second() -> str:
            second_submitted.set()
            return await provider.transcribe(audio)

        second = asyncio.create_task(transcribe_second())
        await second_submitted.wait()
        await asyncio.sleep(0)

        with model.state_lock:
            assert model.call_count == 1
            assert model.maximum_active_calls == 1

        model.release_first.set()
        assert await asyncio.gather(first, second) == ["first", "second"]
        assert model.maximum_active_calls == 1

    asyncio.run(exercise())


def test_initialization_failure_is_wrapped_and_retry_does_not_hang() -> None:
    async def exercise() -> None:
        factory = FakeFactory(RuntimeError("model missing"))
        provider = FasterWhisperSTTProvider("missing", model_factory=factory)
        audio = AudioSegment((pcm_frame([1]),))

        for _ in range(2):
            with pytest.raises(STTError, match="model missing"):
                await asyncio.wait_for(provider.transcribe(audio), 0.5)
        assert len(factory.calls) == 2

    asyncio.run(exercise())


def test_inference_failure_is_wrapped_and_later_call_succeeds() -> None:
    async def exercise() -> None:
        model = FakeModel([RuntimeError("decode broke"), ["recovered"]])
        provider = FasterWhisperSTTProvider(
            "model", model_factory=FakeFactory(model)
        )
        audio = AudioSegment((pcm_frame([1]),))

        with pytest.raises(STTError, match="decode broke"):
            await provider.transcribe(audio)
        assert await provider.transcribe(audio) == "recovered"

    asyncio.run(exercise())


def test_implementation_satisfies_existing_stt_contract() -> None:
    async def consume(stt: STTProvider, audio: AudioSegment) -> str:
        return await stt.transcribe(audio)

    async def exercise() -> None:
        provider = FasterWhisperSTTProvider(
            "model", model_factory=FakeFactory(FakeModel([["contract"]]))
        )
        assert await consume(provider, AudioSegment((pcm_frame([1]),))) == "contract"

    asyncio.run(exercise())


def test_default_loader_requires_local_model_files(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class ModelConstructor:
        def __new__(cls, path: str, **options: Any) -> object:
            calls.append((path, options))
            return object()

    fake_module = type("FakeFasterWhisper", (), {"WhisperModel": ModelConstructor})
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    _load_local_model("/models/tiny", "cpu", "int8")

    assert calls == [
        (
            "/models/tiny",
            {"device": "cpu", "compute_type": "int8", "local_files_only": True},
        )
    ]


def test_cancellation_does_not_release_model_while_worker_is_running() -> None:
    class BlockingModel(FakeModel):
        def __init__(self) -> None:
            super().__init__([["cancelled"], ["reused"]])
            self.started = threading.Event()
            self.release = threading.Event()

        def transcribe(self, audio: Any, *, vad_filter: bool) -> tuple[Any, None]:
            self.started.set()
            self.release.wait(timeout=1)
            return super().transcribe(audio, vad_filter=vad_filter)

    async def exercise() -> None:
        model = BlockingModel()
        provider = FasterWhisperSTTProvider(
            "model", model_factory=FakeFactory(model)
        )
        audio = AudioSegment((pcm_frame([1]),))
        cancelled = asyncio.create_task(provider.transcribe(audio))
        await asyncio.to_thread(model.started.wait, 0.5)
        cancelled.cancel()
        asyncio.get_running_loop().call_later(0.01, model.release.set)
        with pytest.raises(asyncio.CancelledError):
            await cancelled

        assert await provider.transcribe(audio) == "reused"

    asyncio.run(exercise())
