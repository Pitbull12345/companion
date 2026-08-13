import asyncio
from collections.abc import Iterable, Sequence

import pytest

from companion.audio.errors import VADError
from companion.audio.interfaces import AudioFrame, AudioSegment, AudioSource, VADProvider
from companion.audio.silero_vad import SileroInferenceEngine, SileroVADProvider


def frame(label: int, samples: int = 4, **metadata: int) -> AudioFrame:
    data = int(label).to_bytes(2, "little", signed=True) * samples
    return AudioFrame(data=data, **metadata)


class FakeSource:
    def __init__(self, frames: Iterable[AudioFrame]) -> None:
        self.frames = iter(frames)
        self.read_count = 0

    async def read_frame(self) -> AudioFrame:
        self.read_count += 1
        return next(self.frames)


class FakeInference:
    def __init__(self, probabilities: Iterable[float | Exception]) -> None:
        self.probabilities = iter(probabilities)
        self.windows: list[tuple[float, ...]] = []
        self.reset_count = 0

    def speech_probability(self, samples: Sequence[float]) -> float:
        self.windows.append(tuple(samples))
        result = next(self.probabilities)
        if isinstance(result, Exception):
            raise result
        return result

    def reset(self) -> None:
        self.reset_count += 1


def provider(inference: FakeInference, **options: float | int) -> SileroVADProvider:
    settings: dict[str, float | int] = {
        "inference_window_samples": 4,
        "start_confirmation_windows": 1,
        "pre_speech_seconds": 0.0005,
        "trailing_silence_seconds": 0.0005,
        "max_utterance_seconds": 1.0,
    }
    settings.update(options)
    return SileroVADProvider(inference, **settings)


def labels(segment: AudioSegment) -> list[int]:
    return [int.from_bytes(item.data[:2], "little", signed=True) for item in segment.frames]


def test_silence_speech_and_trailing_silence_returns_chronological_segment() -> None:
    async def exercise() -> None:
        inference = FakeInference([0.0, 0.8, 0.9, 0.0, 0.0])
        vad = provider(inference)

        result = await vad.capture_utterance(FakeSource(frame(i) for i in range(1, 6)))

        assert labels(result) == [1, 2, 3, 4, 5]

    asyncio.run(exercise())


def test_pre_speech_history_is_bounded_during_long_silence() -> None:
    async def exercise() -> None:
        silence_count = 1_000
        inference = FakeInference([0.0] * silence_count + [0.9, 0.0, 0.0])
        vad = provider(inference, pre_speech_seconds=0.0005)
        frames = [frame(i) for i in range(1, silence_count + 4)]

        result = await vad.capture_utterance(FakeSource(frames))

        assert labels(result) == frames_to_labels(frames[-4:])
        assert len(result.frames) == 4

    asyncio.run(exercise())


def frames_to_labels(frames: Sequence[AudioFrame]) -> list[int]:
    return [int.from_bytes(item.data[:2], "little", signed=True) for item in frames]


def test_maximum_duration_stops_extremely_long_speech() -> None:
    async def exercise() -> None:
        inference = FakeInference([0.9] * 100)
        vad = provider(
            inference,
            pre_speech_seconds=0.0,
            max_utterance_seconds=0.00075,
        )
        source = FakeSource(frame(i) for i in range(1, 101))

        result = await vad.capture_utterance(source)

        assert labels(result) == [1, 2, 3]
        assert source.read_count == 3

    asyncio.run(exercise())


def test_varying_frame_lengths_are_rechunked_for_inference() -> None:
    async def exercise() -> None:
        inference = FakeInference([0.9, 0.9, 0.0, 0.0])
        vad = provider(inference)
        source = FakeSource([frame(1, 1), frame(2, 7), frame(3, 3), frame(4, 5)])

        result = await vad.capture_utterance(source)

        assert [len(window) for window in inference.windows] == [4, 4, 4, 4]
        assert labels(result) == [1, 2, 3, 4]

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("bad_frame", "message"),
    [
        (frame(1, sample_rate=8_000), "sample rate"),
        (frame(1, channels=2), "channel count"),
        (frame(1, sample_width=1), "sample width"),
        (AudioFrame(b"\x00"), "sample-aligned"),
    ],
)
def test_invalid_audio_format_fails_clearly(
    bad_frame: AudioFrame, message: str
) -> None:
    async def exercise() -> None:
        inference = FakeInference([])
        with pytest.raises(VADError, match=message):
            await provider(inference).capture_utterance(FakeSource([bad_frame]))
        assert inference.reset_count == 2

    asyncio.run(exercise())


def test_inference_failure_propagates_and_later_capture_is_clean() -> None:
    async def exercise() -> None:
        inference = FakeInference([RuntimeError("model broke"), 0.9, 0.0, 0.0])
        vad = provider(inference)

        with pytest.raises(VADError, match="model broke"):
            await vad.capture_utterance(FakeSource([frame(1)]))
        result = await vad.capture_utterance(FakeSource([frame(2), frame(3), frame(4)]))

        assert labels(result) == [2, 3, 4]
        assert inference.reset_count == 4

    asyncio.run(exercise())


def test_repeated_captures_reset_detector_and_model_state() -> None:
    async def exercise() -> None:
        inference = FakeInference([0.9, 0.0, 0.0, 0.9, 0.0, 0.0])
        vad = provider(inference)

        first = await vad.capture_utterance(FakeSource([frame(1), frame(2), frame(3)]))
        second = await vad.capture_utterance(FakeSource([frame(4), frame(5), frame(6)]))

        assert labels(first) == [1, 2, 3]
        assert labels(second) == [4, 5, 6]
        assert inference.reset_count == 4

    asyncio.run(exercise())


def test_cancellation_resets_state_and_provider_remains_reusable() -> None:
    class BlockingSource:
        async def read_frame(self) -> AudioFrame:
            await asyncio.Future()
            raise AssertionError("unreachable")

    async def exercise() -> None:
        inference = FakeInference([0.9, 0.0, 0.0])
        vad = provider(inference)
        pending = asyncio.create_task(vad.capture_utterance(BlockingSource()))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

        result = await vad.capture_utterance(
            FakeSource([frame(1), frame(2), frame(3)])
        )
        assert labels(result) == [1, 2, 3]
        assert inference.reset_count == 4

    asyncio.run(exercise())


def test_implementation_satisfies_existing_vad_contract() -> None:
    async def consume(vad: VADProvider, source: AudioSource) -> AudioSegment:
        return await vad.capture_utterance(source)

    async def exercise() -> None:
        inference = FakeInference([0.9, 0.0, 0.0])
        result = await consume(
            provider(inference), FakeSource([frame(1), frame(2), frame(3)])
        )
        assert labels(result) == [1, 2, 3]

    asyncio.run(exercise())


def test_real_silero_configuration_requires_supported_window_size() -> None:
    with pytest.raises(ValueError, match="512-sample"):
        SileroVADProvider(inference_window_samples=256)


def test_real_silero_engine_rejects_unsupported_window_size() -> None:
    class UnusedModel:
        def reset_states(self) -> None:
            pass

    class UnusedTorch:
        float32 = object()

        def tensor(self, samples: Sequence[float], dtype: object) -> object:
            raise AssertionError("unsupported input must be rejected before conversion")

    engine = SileroInferenceEngine(UnusedModel(), UnusedTorch())

    with pytest.raises(VADError, match="exactly 512"):
        engine.speech_probability([0.0] * 256)
