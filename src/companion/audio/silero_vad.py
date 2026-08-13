import asyncio
import struct
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Protocol

from companion.audio.errors import VADError
from companion.audio.interfaces import AudioFrame, AudioSegment, AudioSource


class SpeechProbabilityEngine(Protocol):
    """Small boundary around stateful streaming VAD inference."""

    def speech_probability(self, samples: Sequence[float]) -> float: ...

    def reset(self) -> None: ...


class SileroInferenceEngine:
    """Synchronous Silero inference adapter for small streaming windows."""

    WINDOW_SAMPLES = 512

    def __init__(self, model: Any, torch_module: Any) -> None:
        self._model = model
        self._torch = torch_module

    @classmethod
    def load(cls) -> "SileroInferenceEngine":
        """Load the model bundled with the installed silero-vad package."""
        try:
            import torch
            from silero_vad import load_silero_vad

            model = load_silero_vad()
        except Exception as exc:
            raise VADError(f"could not load Silero VAD model: {exc}") from exc
        return cls(model, torch)

    def speech_probability(self, samples: Sequence[float]) -> float:
        if len(samples) != self.WINDOW_SAMPLES:
            raise VADError(
                "Silero VAD at 16 kHz requires exactly 512 samples per inference"
            )
        tensor = self._torch.tensor(samples, dtype=self._torch.float32)
        return float(self._model(tensor, 16_000).item())

    def reset(self) -> None:
        self._model.reset_states()


class SileroVADProvider:
    """Detect one utterance from streaming 16 kHz mono PCM audio.

    Silero inference is synchronous because each fixed-size streaming window is
    small. No background reader or inference tasks are created.
    """

    def __init__(
        self,
        inference: SpeechProbabilityEngine | None = None,
        *,
        speech_start_threshold: float = 0.6,
        speech_end_threshold: float = 0.35,
        trailing_silence_seconds: float = 0.5,
        pre_speech_seconds: float = 0.25,
        max_utterance_seconds: float = 30.0,
        inference_window_samples: int = 512,
        start_confirmation_windows: int = 2,
        speech_wait_timeout: float | None = None,
        inference_loader: Callable[[], SpeechProbabilityEngine] | None = None,
    ) -> None:
        if not 0.0 <= speech_end_threshold <= speech_start_threshold <= 1.0:
            raise ValueError("speech thresholds must satisfy 0 <= end <= start <= 1")
        if trailing_silence_seconds <= 0:
            raise ValueError("trailing_silence_seconds must be positive")
        if pre_speech_seconds < 0:
            raise ValueError("pre_speech_seconds cannot be negative")
        if max_utterance_seconds <= 0:
            raise ValueError("max_utterance_seconds must be positive")
        if inference_window_samples < 1:
            raise ValueError("inference_window_samples must be positive")
        if start_confirmation_windows < 1:
            raise ValueError("start_confirmation_windows must be positive")
        if speech_wait_timeout is not None and speech_wait_timeout <= 0:
            raise ValueError("speech_wait_timeout must be positive")
        if (
            inference is None
            and inference_loader is None
            and inference_window_samples != SileroInferenceEngine.WINDOW_SAMPLES
        ):
            raise ValueError("real Silero inference requires a 512-sample window")

        self._inference = inference
        self._inference_loader = inference_loader or SileroInferenceEngine.load
        self._speech_start_threshold = speech_start_threshold
        self._speech_end_threshold = speech_end_threshold
        self._trailing_silence_seconds = trailing_silence_seconds
        self._pre_speech_seconds = min(pre_speech_seconds, max_utterance_seconds)
        self._max_utterance_seconds = max_utterance_seconds
        self._inference_window_samples = inference_window_samples
        self._start_confirmation_windows = start_confirmation_windows
        self._speech_wait_timeout = speech_wait_timeout

    def _engine(self) -> SpeechProbabilityEngine:
        if self._inference is None:
            self._inference = self._inference_loader()
        return self._inference

    @staticmethod
    def _validate_frame(frame: AudioFrame) -> None:
        if frame.sample_rate != 16_000:
            raise VADError(
                f"unsupported VAD sample rate {frame.sample_rate}; expected 16000 Hz"
            )
        if frame.channels != 1:
            raise VADError(
                f"unsupported VAD channel count {frame.channels}; expected mono"
            )
        if frame.sample_width != 2:
            raise VADError(
                f"unsupported VAD sample width {frame.sample_width}; expected 2 bytes"
            )
        if len(frame.data) % 2:
            raise VADError("malformed PCM data: byte length is not sample-aligned")

    @staticmethod
    def _normalized_samples(data: bytes) -> Iterator[float]:
        for (sample,) in struct.iter_unpack("<h", data):
            yield sample / 32768.0

    @staticmethod
    def _frame_duration(frame: AudioFrame) -> float:
        return len(frame.data) / (frame.sample_rate * frame.channels * frame.sample_width)

    async def capture_utterance(self, source: AudioSource) -> AudioSegment:
        try:
            engine = self._engine()
            engine.reset()
        except VADError:
            raise
        except Exception as exc:
            raise VADError(f"could not reset Silero VAD state: {exc}") from exc

        pre_speech: deque[tuple[AudioFrame, float]] = deque()
        pre_speech_duration = 0.0
        utterance: list[AudioFrame] = []
        utterance_duration = 0.0
        inference_window: list[float] = []
        speaking = False
        start_windows = 0
        silence_duration = 0.0
        loop = asyncio.get_running_loop()
        wait_deadline = (
            None
            if self._speech_wait_timeout is None
            else loop.time() + self._speech_wait_timeout
        )

        try:
            while True:
                try:
                    if wait_deadline is None or speaking:
                        frame = await source.read_frame()
                    else:
                        remaining = wait_deadline - loop.time()
                        if remaining <= 0:
                            raise VADError("timed out waiting for speech")
                        frame = await asyncio.wait_for(source.read_frame(), remaining)
                except TimeoutError as exc:
                    raise VADError("timed out waiting for speech") from exc

                self._validate_frame(frame)
                duration = self._frame_duration(frame)
                if speaking:
                    if utterance and utterance_duration + duration > self._max_utterance_seconds:
                        return AudioSegment(tuple(utterance))
                    utterance.append(frame)
                    utterance_duration += duration
                else:
                    pre_speech.append((frame, duration))
                    pre_speech_duration += duration
                    while len(pre_speech) > 1 and pre_speech_duration > self._pre_speech_seconds:
                        _old_frame, old_duration = pre_speech.popleft()
                        pre_speech_duration -= old_duration

                utterance_complete = False
                for sample in self._normalized_samples(frame.data):
                    inference_window.append(sample)
                    if len(inference_window) < self._inference_window_samples:
                        continue
                    try:
                        probability = engine.speech_probability(inference_window)
                    except Exception as exc:
                        raise VADError(f"Silero VAD inference failed: {exc}") from exc
                    inference_window.clear()

                    if not speaking:
                        if probability >= self._speech_start_threshold:
                            start_windows += 1
                        else:
                            start_windows = 0
                        if start_windows >= self._start_confirmation_windows:
                            speaking = True
                            utterance = [item for item, _duration in pre_speech]
                            utterance_duration = pre_speech_duration
                            pre_speech.clear()
                            pre_speech_duration = 0.0
                            silence_duration = 0.0
                    elif probability < self._speech_end_threshold:
                        silence_duration += (
                            self._inference_window_samples / frame.sample_rate
                        )
                        if silence_duration >= self._trailing_silence_seconds:
                            utterance_complete = True
                            break
                    else:
                        silence_duration = 0.0

                if utterance_complete or (
                    speaking and utterance_duration >= self._max_utterance_seconds
                ):
                    return AudioSegment(tuple(utterance))
        finally:
            try:
                engine.reset()
            except Exception:
                # Do not mask success, cancellation, or the original provider failure.
                pass
