# TASK-0003 — Silero VAD

## Status

Done

## Problem

Companion can now capture real microphone audio as provider-neutral
AudioFrame objects, but it cannot determine when the user starts and
stops speaking.

AssistantRuntime already depends on the provider-neutral VADProvider
contract:

    AudioSource
        ↓
    VADProvider.capture_utterance()
        ↓
    AudioSegment

This task implements that boundary using Silero VAD.

The provider must consume streaming AudioFrame objects and return one
bounded AudioSegment representing a detected user utterance.

## Desired outcome

Companion has a Silero-backed VADProvider that:

- consumes 16 kHz mono signed 16-bit PCM AudioFrame objects;
- detects speech start;
- accumulates the spoken utterance;
- detects speech end after configurable trailing silence;
- returns one AudioSegment;
- remains provider-neutral to AssistantRuntime;
- does not require real microphone hardware or a downloaded model during
  normal automated tests.

## System position

    Microphone
        ↓
    SoundDeviceAudioSource
        ↓
    AudioFrame
        ↓
    SileroVADProvider
        ↓
    AudioSegment
        ↓
    STTProvider          # TASK-0004

This task ends at AudioSegment creation.

## Existing contracts

Preserve the existing provider-neutral interfaces in
`companion.audio.interfaces`.

In particular:

    class VADProvider(Protocol):
        async def capture_utterance(
            self,
            source: AudioSource,
        ) -> AudioSegment: ...

Do not make AssistantRuntime depend directly on Silero.

Do not introduce Silero-specific types into core runtime interfaces.

## Requirements

Implement a concrete Silero-backed VADProvider.

The provider must:

1. consume AudioFrame objects from an AudioSource;
2. validate that incoming audio is compatible with the VAD input format;
3. convert signed 16-bit PCM bytes into normalized model input;
4. feed audio to a Silero inference boundary;
5. detect speech using configurable probability thresholds;
6. wait indefinitely for speech by default unless explicitly configured
   otherwise;
7. preserve a small configurable amount of audio immediately before speech
   begins;
8. accumulate speech frames;
9. consider the utterance complete after configurable trailing silence;
10. impose a configurable maximum utterance duration;
11. return an AudioSegment containing frames in chronological order;
12. reset per-utterance state before capturing the next utterance.

The implementation must not assume AudioSource frames are all the same byte
length.

## Silero inference boundary

Keep model inference behind a small injectable abstraction.

Normal VAD state-machine tests must be able to provide deterministic
speech probabilities without loading the real Silero model.

For example, the implementation may use an injected callable/protocol that
accepts normalized PCM samples and returns a speech probability.

The precise internal API is implementation-defined, but core VAD logic and
Silero model loading must remain separable.

## Audio format

Expected input:

- 16,000 Hz;
- mono;
- signed 16-bit PCM;
- sample_width = 2.

Unsupported AudioFrame metadata must fail clearly rather than being silently
resampled or reformatted.

Resampling is not part of this task.

The provider must handle arbitrary AudioFrame boundaries. If Silero requires
a fixed inference window, buffer/rechunk incoming PCM internally without
assuming microphone callbacks already match that window.

## Speech detection

Expose configurable values for at least:

- speech-start threshold;
- speech-end/trailing-silence duration;
- pre-speech buffer duration;
- maximum utterance duration.

Reasonable defaults may be chosen.

Speech should not begin from a single accidental model spike if a small
confirmation strategy is necessary for reliable operation.

Do not add complex adaptive-noise processing in this task.

## Lifecycle and ownership

SileroVADProvider does not own the AudioSource.

It must not close the supplied AudioSource.

Per-utterance buffers and detector state belong to the VAD provider and must
be reset between capture_utterance() calls.

If the real Silero inference engine has internal recurrent/model state, that
state must be reset appropriately between utterances.

Model resources may remain loaded across utterances.

## Concurrency and async behavior

`capture_utterance()` is asynchronous because AudioSource.read_frame() is
asynchronous.

Silero inference must not create unbounded background tasks.

Do not create independent microphone reader threads or queues.

The VAD provider consumes directly from the provided AudioSource.

If model inference is sufficiently small for streaming use, synchronous
inference inside capture_utterance() is acceptable for this task. Document
the decision.

Cancellation of capture_utterance() must propagate normally and must not
leave corrupted per-utterance state.

## Buffering and backpressure

All VAD-owned buffering must be bounded.

Bound at least:

- pre-speech history;
- current utterance by maximum duration;
- any rechunking/inference buffer.

Do not accumulate silence indefinitely while waiting for speech.

Only the configured pre-speech history should be retained before speech.

Frames returned in AudioSegment must remain in chronological order.

## Resource limits

Memory use must remain bounded while:

- waiting indefinitely for speech;
- receiving continuous silence;
- receiving an extremely long speech stream.

Maximum utterance duration must prevent an unlimited AudioSegment.

## Failure behavior

Clearly fail on:

- unsupported sample rate;
- unsupported channel count;
- unsupported sample width;
- malformed PCM sample alignment;
- inference/model failure.

A failed inference must not turn into an indefinite wait.

Per-utterance state must be cleaned/reset after success, failure, or
cancellation so a later capture can begin cleanly where appropriate.

Provider-neutral audio/VAD errors should live outside the concrete Silero
provider module.

## Explicit non-goals

Do not implement:

- Whisper;
- faster-whisper;
- transcription;
- resampling;
- microphone selection UI;
- wake-word detection;
- TTS;
- LLM providers;
- speaker output;
- barge-in;
- AssistantRuntime redesign;
- semantic memory;
- episodic memory;
- systemd integration.

Do not download a Silero model during normal tests.

## Tests

### Unit tests

Use fake AudioSource objects and fake inference/model components.

Test at least:

1. silence followed by speech followed by trailing silence returns one
   AudioSegment;
2. returned frames remain in chronological order;
3. pre-speech buffering includes only the configured bounded history;
4. continuous silence does not create unbounded retained audio;
5. extremely long speech stops at maximum utterance duration;
6. varying AudioFrame byte lengths are handled correctly;
7. unsupported sample rate fails clearly;
8. unsupported channel count fails clearly;
9. unsupported sample width fails clearly;
10. malformed PCM length fails clearly;
11. inference failure propagates clearly;
12. repeated capture_utterance() calls reset detector state;
13. cancellation leaves the provider reusable or explicitly failed according
    to the documented design.

### Contract test

Verify the implementation can be consumed through the existing VADProvider
contract.

### Integration test

Using:

- a fake AudioSource;
- deterministic fake speech probabilities;

exercise:

    AudioSource
        ↓
    SileroVADProvider
        ↓
    AudioSegment

No microphone or downloaded model may be required.

### Long-running/system scenarios

Test:

- many silence frames before speech while memory remains bounded;
- speech longer than maximum duration;
- repeated utterances;
- inference failure followed by another capture where supported.

## Hardware/model diagnostic

An optional diagnostic may exercise the real Silero implementation against
real microphone audio.

It must be excluded from the normal test gate and must not run during:

    ./scripts/check

## Acceptance criteria

TASK-0003 is complete when:

- a concrete Silero-backed VADProvider exists;
- core runtime still depends only on VADProvider;
- arbitrary microphone frame boundaries are handled;
- pre-speech buffering is bounded;
- silence waiting is bounded in memory;
- utterance duration is bounded;
- trailing silence terminates an utterance;
- provider state resets correctly;
- real Silero inference is isolated from deterministic VAD logic;
- normal tests need no microphone;
- normal tests need no downloaded model;
- no STT functionality is added;
- all existing tests continue to pass;
- ./scripts/check succeeds.

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed;
2. VAD state-machine behavior implemented;
3. Silero inference integration;
4. dependency/model changes;
5. lifecycle/state-reset behavior;
6. buffering/resource limits;
7. tests added;
8. ./scripts/check result;
9. architectural deviations;
10. deferred work.
