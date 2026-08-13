# TASK-0002 — Real microphone AudioSource

## Status

Ready

## Problem

Companion now has a provider-neutral speech runtime and an AudioSource
interface, but the only audio sources used so far are test fakes.

The application therefore has no way to receive actual microphone audio.

This task adds the first real external provider: a microphone-backed
AudioSource.

The provider must preserve the existing architecture:

    Microphone
        ↓
    SoundDeviceAudioSource
        ↓
      AudioFrame
        ↓
     VADProvider

This task stops at AudioFrame production.

## Desired outcome

A real microphone implementation can asynchronously supply AudioFrame
instances containing raw microphone PCM.

Normal automated tests must prove the implementation without requiring an
actual microphone.

An optional hardware diagnostic may verify capture manually.

## Read before implementation

- `AGENTS.md`
- `docs/architecture/system.md`
- `docs/architecture/speech-pipeline.md`
- `docs/architecture/providers.md`
- `src/companion/audio/interfaces.py`
- `flake.nix`

## Existing contract

AudioSource currently exposes:

    async read_frame() -> AudioFrame

AudioFrame currently contains:

- data: bytes
- sample_rate
- channels
- sample_width

Do not redesign this contract unless implementation proves it is necessary.

If a contract change is necessary, explain why before broadening the change.

## Provider

Use `sounddevice`.

Prefer `sounddevice.RawInputStream` because Companion's AudioFrame already
stores raw bytes and RawInputStream provides buffer data without requiring
NumPy.

The provider implementation should live under `src/companion/audio/`.

A reasonable module name is:

    src/companion/audio/sounddevice_source.py

## Audio format

Default requested format:

- sample rate: 16000 Hz
- channels: 1
- sample type: signed 16-bit PCM
- sample width: 2 bytes

The provider must accurately populate AudioFrame metadata.

Do not implement resampling in this task.

If a device cannot support the requested configuration, fail clearly rather
than silently changing the audio format.

## Async boundary

sounddevice callbacks are not asyncio coroutines.

The implementation must safely bridge microphone callback data into the
asyncio-facing `read_frame()` interface.

Do not block the asyncio event loop waiting synchronously for microphone data.

Do not expose sounddevice callback objects outside the concrete provider.

## Lifecycle

The concrete microphone source must provide explicit resource cleanup.

Opening and closing the underlying audio stream must be deterministic.

After close:

- the underlying stream must be stopped/closed;
- pending reads must not silently hang forever;
- repeated cleanup should be safe where practical.

Do not modify AssistantRuntime solely to manage microphone lifecycle in this
task.

## Errors

Introduce a small Companion-level audio exception if useful.

Provider-specific sounddevice exceptions should not leak unnecessarily through
the rest of the application.

At minimum handle:

- microphone/stream creation failure;
- attempts to read from a closed source;
- callback/stream failure where observable.

Error handling must not silently discard fatal provider failures.

## Dependency/package requirements

Add sounddevice through the project's normal package environment.

The application must continue to work through Nix.

Do not instruct users or tests to `pip install` dependencies manually.

Update Nix/package metadata as needed so that:

    nix develop

contains the dependency and the packaged application can import it.

The current Nix package has no runtime sounddevice dependency yet.

## Required tests

Automated tests must NOT require real audio hardware.

Use an injectable/fake stream or backend boundary.

At minimum test:

### Frame production

Given fake microphone callback data:

When `read_frame()` completes:

Then it returns an AudioFrame containing:

- the same PCM bytes;
- the configured sample rate;
- the configured channel count;
- sample_width == 2.

### Stream configuration

Verify that the underlying input stream is requested with:

- configured sample rate;
- configured channel count;
- int16 format.

### Cleanup

Given an opened source:

When it is closed:

Then the underlying stream is stopped/closed.

### Initialization failure

Given a backend that fails while opening the microphone:

Then the concrete provider raises an appropriate Companion audio error.

### Contract compatibility

The concrete provider must remain usable anywhere an AudioSource is expected.

## Optional hardware diagnostic

A hardware-marked/manual test or small diagnostic may:

1. open the default microphone;
2. capture several frames;
3. report frame byte counts and metadata;
4. exit cleanly.

It must not run as part of `./scripts/check`.

Do not add speech recognition to this diagnostic.

## Explicit non-goals

Do NOT implement:

- Silero VAD;
- Whisper;
- faster-whisper;
- speech transcription;
- resampling;
- wake words;
- TTS;
- speaker output;
- Ollama;
- LLM integration;
- barge-in;
- UI;
- microphone selection UI;
- systemd integration.

Do not modify AssistantRuntime unless required to preserve an existing
contract.

## Acceptance criteria

TASK-0002 is complete when:

1. Companion has a real microphone-backed AudioSource.
2. It produces raw PCM AudioFrame objects.
3. The asyncio-facing API does not block on synchronous microphone reads.
4. Resource cleanup is deterministic.
5. Failure cases produce useful errors.
6. Normal tests require no physical microphone.
7. Existing TASK-0001 tests still pass.
8. `./scripts/check` passes.
9. `nix develop` and the packaged application have access to sounddevice.

## Verification

Run:

    ./scripts/check

The task is not complete if the normal verification gate fails.

## Completion report

Report:

1. files changed;
2. dependency changes;
3. microphone implementation behavior;
4. lifecycle behavior;
5. tests added;
6. verification results;
7. architectural deviations;
8. anything intentionally deferred.
