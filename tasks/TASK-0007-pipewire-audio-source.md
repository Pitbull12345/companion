# TASK-0007 — PipeWire Audio Source

## Status
Ready

## Problem

Companion currently uses SoundDeviceAudioSource for microphone capture.

On Fedora, PortAudio/sounddevice exposes raw ALSA devices and does not follow
PipeWire/WirePlumber desktop routing. Device indexes are unstable, and the
available hardware inputs do not accept Companion's internal 16 kHz mono s16
format directly.

Real hardware testing proved that PipeWire can capture from the Fedora default
microphone and provide normalized 16 kHz mono signed 16-bit PCM.

## Desired outcome

Implement a Linux PipeWireAudioSource that satisfies the existing AudioSource
contract and uses the system default PipeWire microphone.

Real path:

Fedora default microphone
    ↓
pw-cat --record --raw
    ↓
16 kHz / mono / s16
    ↓
small AudioFrames
    ↓
Silero VAD

## Existing architecture

Preserve the provider-neutral boundary:

AudioSource
    ↓
VADProvider
    ↓
STTProvider

AssistantRuntime and Silero must not depend directly on PipeWire.

Keep SoundDeviceAudioSource available as another backend.

## Requirements

### PipeWire capture

Implement PipeWireAudioSource using the system PipeWire client.

Use raw PCM capture with:

- sample rate: 16000 Hz
- channels: 1
- format: signed 16-bit PCM
- default PipeWire/WirePlumber source
- no hard-coded physical microphone
- no temporary files

Conceptually:

    pw-cat --record --raw --rate 16000 --channels 1 --format s16 -

### AudioFrame output

PipeWireAudioSource must return existing provider-neutral AudioFrame objects.

Returned frames must contain:

- raw PCM bytes
- sample_rate = 16000
- channels = 1
- sample_width = 2

Use a reasonable fixed frame size suitable for continuous VAD processing.

Do not return arbitrarily large chunks.

### Streaming behavior

The provider must:

- start capture lazily
- continuously read PCM from the subprocess
- return one AudioFrame per read_frame() call
- preserve byte ordering
- never silently lose frame alignment

No temporary WAV or raw files.

### Lifecycle and ownership

PipeWireAudioSource owns its pw-cat capture subprocess.

Provide explicit lifecycle behavior for:

- start
- read_frame
- close

close must be safe to call multiple times.

The provider must not leave orphaned pw-cat processes.

### Async behavior

Do not block the asyncio event loop.

Use asyncio subprocess APIs.

Do not introduce unnecessary permanent background tasks.

### Buffering and backpressure

Do not introduce unbounded buffering.

Prefer direct reads from the subprocess stdout where practical.

If buffering is required, it must be bounded and documented.

### Cancellation

Cancellation during startup or read must:

- clean up the subprocess safely where necessary
- propagate asyncio.CancelledError
- not leave locks, readers, or subprocesses in an inconsistent state

### Failure behavior

Surface failures as provider-neutral AudioError.

Handle clearly:

- pw-cat unavailable
- process startup failure
- subprocess exits unexpectedly
- stdout unavailable
- malformed/incomplete PCM frame
- read failure
- close/termination failure

A fatal failure must not turn later read_frame() calls into indefinite waits.

### Testability

Subprocess creation must be injectable/testable.

Normal tests must require:

- no microphone
- no PipeWire server
- no physical audio device
- no network

Use fake subprocess/stdout implementations.

## Tests

Add deterministic tests covering:

- existing AudioSource contract
- correct pw-cat command
- no physical target/source hard-coded
- requested 16000 Hz
- requested mono
- requested s16
- PCM bytes become correct AudioFrame metadata
- frame sizing
- repeated reads preserve ordering
- startup failure
- pw-cat unavailable
- unexpected process exit
- read failure
- cancellation
- idempotent close
- subprocess terminated and waited for during cleanup
- no hardware interaction in normal test suite

## Real diagnostic

Provide or document an optional manual diagnostic that captures from the Fedora
default PipeWire microphone and confirms real AudioFrames are produced.

It must not run as part of ./scripts/check.

## Explicit non-goals

Do NOT implement:

- TTS changes
- PipeWireAudioOutput changes
- character packages
- ElevenLabs
- GUI
- audio asset importing
- codecs
- MP3/OGG decoding
- barge-in
- streaming STT
- memory changes
- tool calling

## Acceptance criteria

- PipeWireAudioSource implements AudioSource
- Linux capture follows the system default PipeWire source
- no hard-coded microphone device index
- output is 16 kHz mono s16 PCM
- AudioFrames are bounded and correctly aligned
- subprocess lifecycle is safe
- cancellation is safe
- normal tests need no hardware
- ./scripts/check passes
- real PipeWire microphone diagnostic succeeds

## Verification

Run:

    ./scripts/check

## Completion report

Codex must summarize:

- files changed
- capture architecture
- frame size choice
- lifecycle decisions
- buffering/backpressure behavior
- cancellation behavior
- tests added
- verification results
- deferred work or remaining risks
