# TASK-0004 — faster-whisper STT

## Status

Ready

## Problem

Companion can capture microphone audio and use Silero VAD to produce one
AudioSegment representing a spoken utterance.

It cannot yet convert that AudioSegment into text.

The existing runtime already depends on the provider-neutral STTProvider
contract:

    AudioSegment
        ↓
    STTProvider.transcribe()
        ↓
    str

This task implements that contract with faster-whisper.

## Desired outcome

Companion can convert a 16 kHz mono signed 16-bit PCM AudioSegment into text
using a locally installed faster-whisper model.

The implementation must remain provider-neutral to AssistantRuntime and must
not require a real model during normal automated tests.

## System position

    Microphone
        ↓
    SoundDeviceAudioSource
        ↓
    SileroVADProvider
        ↓
    AudioSegment
        ↓
    FasterWhisperSTTProvider
        ↓
    str
        ↓
    AssistantRuntime

This task ends at transcription text.

## Existing contracts

Preserve:

    class STTProvider(Protocol):
        async def transcribe(self, audio: AudioSegment) -> str: ...

Do not introduce faster-whisper-specific objects into runtime interfaces.

## Requirements

Implement FasterWhisperSTTProvider.

It must validate that every AudioFrame in the AudioSegment is 16,000 Hz,
mono, signed 16-bit PCM with sample_width=2.

It must reject inconsistent or malformed frames clearly.

It must concatenate the segment's PCM data in chronological order and convert
signed 16-bit PCM into the normalized one-dimensional float audio input
expected by faster-whisper.

An empty AudioSegment must fail clearly or return an explicitly documented
empty result. Do not allow ambiguous behavior.

The provider must load its Whisper model lazily or during explicit provider
initialization and reuse that model across transcriptions.

Model loading must not silently require the network during normal Companion
runtime. Support a local model directory or use faster-whisper's offline /
local-files-only behavior. If the configured model is not locally available,
fail clearly with an STT-specific error.

Model acquisition may be an explicit developer/setup action, but it must not
happen implicitly during ordinary automated tests.

The model name/path, device, and compute type must be configurable at provider
construction.

Do not hard-code CUDA. CPU operation must be supported.

For this task, do not enable faster-whisper's built-in VAD filter. Companion
already owns utterance detection through SileroVADProvider.

Join the text from all returned transcription segments into one normalized
string while preserving spoken order.

## Lifecycle and ownership

FasterWhisperSTTProvider owns the faster-whisper model instance.

The model should be reused between calls rather than loaded for every
utterance.

There is no requirement in this task to unload the model between turns.

A model initialization failure must leave the provider in a clear state and
must not cause later calls to hang indefinitely.

## Concurrency and async behavior

STTProvider.transcribe() is asynchronous, while faster-whisper inference is
synchronous and potentially expensive.

Do not run model loading or transcription inference directly on the asyncio
event loop.

Use an appropriate bounded worker/thread boundary such as asyncio.to_thread()
for synchronous model work.

Important: faster-whisper returns transcription segments lazily. The returned
segment iterator must be fully consumed inside the worker boundary. Do not
return the generator to the asyncio event loop and iterate it there.

Do not create an unbounded number of background transcription jobs.

Document whether concurrent transcribe() calls are supported or serialized.

Cancellation must not corrupt provider state.

## Buffering and resource limits

AudioSegment already bounds utterance duration through the VAD layer.

Do not create unnecessary duplicate unbounded buffers.

The PCM-to-model conversion may allocate one contiguous audio array for the
utterance.

Model resources may remain resident for the lifetime of the provider.

## Failure behavior

Create a provider-neutral STT error type under companion.audio.errors.

Clearly wrap failures from model initialization and transcription.

Malformed audio metadata or PCM must fail before invoking the model.

A failed transcription must not leave subsequent transcriptions permanently
blocked.

Do not hide model-not-found/offline failures behind automatic network
downloads.

## Testing boundary

Keep faster-whisper behind an injectable inference/model abstraction so normal
tests can use a fake model.

Normal tests must not require a downloaded Whisper model, microphone, network,
CUDA, Ollama, or API keys.

Test PCM conversion, chronological ordering, validation, text joining, model
reuse, initialization failure, inference failure, repeated transcription,
async worker behavior where practical, and the existing STTProvider contract.

Add an integration test using a fake AudioSegment and fake inference engine:

    AudioSegment
        ↓
    FasterWhisperSTTProvider
        ↓
    text

A separate optional model diagnostic may load a real local faster-whisper
model and transcribe known audio. It must not run during ./scripts/check.

## Explicit non-goals

Do not implement microphone capture, VAD changes, resampling, translation,
word timestamps, diarization, wake words, LLM providers, Ollama integration,
TTS, speaker output, barge-in, memory, tools, UI, or systemd integration.

Do not redesign AssistantRuntime.

## Acceptance criteria

TASK-0004 is complete when FasterWhisperSTTProvider satisfies STTProvider,
converts AudioSegment PCM correctly, performs expensive model work outside the
asyncio event loop, fully consumes faster-whisper's lazy transcription output
inside the worker boundary, supports offline/local model loading, reuses its
model, has deterministic model-free tests, adds no duplicate VAD behavior,
and ./scripts/check passes.

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report changed files, model/dependency handling, PCM conversion,
async/thread behavior, model lifecycle, errors, tests, verification result,
architectural deviations, and deferred work.
