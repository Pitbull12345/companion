# TASK-0006 — Audio Output and Piper TTS

## Status
Ready

## Problem

Companion can currently capture speech, transcribe it, and generate a local
LLM response, but it cannot synthesize or play the response.

Future characters/pets must also be able to use different TTS providers and
play imported audio clips without coupling those features to the runtime.

## Desired outcome

Implement the provider-neutral speech/audio-output foundation and one local
Piper TTS implementation.

The real pipeline should become:

Microphone
→ Silero VAD
→ faster-whisper
→ Ollama
→ Piper TTS
→ AudioOutput
→ speakers

## System position

The runtime must depend on provider-neutral interfaces.

Generated speech and imported character audio must eventually share the same
audio-output layer.

Conceptual boundary:

Text
→ TTSProvider
→ AudioClip
→ AudioOutput
→ speaker

Future:

Imported audio asset
→ AudioClip
→ AudioOutput
→ speaker

## Existing contracts

Follow the provider-neutral architecture established in AGENTS.md and
docs/architecture/.

Do not couple AssistantRuntime directly to Piper or sounddevice playback.

## Requirements

### Audio representation

Create a provider-neutral representation for synthesized/playable audio.

It must include enough information to describe PCM audio, including:

- audio bytes
- sample rate
- channels
- sample width

The representation must not contain Piper-specific types.

### TTSProvider

Maintain or update the existing provider-neutral TTS contract so that a TTS
provider converts text into the neutral audio representation.

Conceptually:

    async def synthesize(text: str) -> AudioClip

Do not make the TTS provider own the physical speaker.

### AudioOutput

Create a provider-neutral AudioOutput contract responsible for playing an
AudioClip.

Conceptually:

    async def play(audio: AudioClip) -> None

### Piper provider

Implement a concrete local Piper TTS provider.

Requirements:

- local voice/model files only
- no runtime voice download
- voice/model loaded once and reused
- expensive synchronous synthesis must not block the asyncio event loop
- provider-neutral errors
- empty text must fail clearly
- repeated calls reuse the provider/model
- cancellation must propagate safely
- no background tasks left running after failure/cancellation

### Speaker output

Implement one concrete local speaker AudioOutput implementation.

Prefer the existing sounddevice dependency where appropriate.

Requirements:

- play the neutral AudioClip
- do not put playback responsibilities inside Piper
- do not block the asyncio coordinator
- surface playback/device failures through provider-neutral audio errors
- cancellation behavior must be deterministic
- no unbounded queues or buffers

## Lifecycle and ownership

Piper owns/reuses its loaded voice/model.

AudioOutput owns access to the playback device.

AssistantRuntime coordinates them but must not know their concrete
implementations.

## Concurrency and async behavior

Model synthesis and blocking playback operations must not block the asyncio
event loop.

Document whether concurrent synthesis/playback is serialized or supported.

Cancellation must not leave a model, playback device, worker, lock, or future
in an inconsistent state.

## Buffering and resource limits

Do not introduce unbounded buffering.

Do not create a permanent background audio worker unless required by the task.

Keep the implementation suitable for future character audio clips.

## Failure behavior

Create/use provider-neutral exceptions for:

- TTS synthesis failure
- malformed/empty synthesized audio
- playback/device failure

Fatal provider failures must never silently become indefinite waits.

## Explicit non-goals

Do NOT implement:

- ElevenLabs
- voice cloning
- character packages
- sprites or GUI
- animation synchronization
- audio asset importing
- tool calling
- memory changes
- streaming LLM responses
- barge-in
- automatic model/voice downloads

Those are future tasks.

## Tests

Normal tests must NOT require:

- speakers
- microphone
- downloaded Piper voices
- network
- Ollama
- hardware

Use fake Piper/model and AudioOutput implementations.

Add tests covering:

- TTSProvider contract
- AudioOutput contract
- text passed correctly to Piper
- synthesized PCM represented correctly as AudioClip
- model/voice reuse
- empty text rejection
- synthesis failure wrapping
- playback failure wrapping
- repeated synthesis
- cancellation
- event-loop/nonblocking boundary where applicable
- speaker implementation configuration boundary using fakes/mocks
- no hardware interaction in normal test suite

## Integration test

Add an integration test using fakes proving:

text
→ TTSProvider
→ AudioClip
→ AudioOutput

No real speaker or model.

## Real diagnostic

Provide or document an optional manual diagnostic for:

text
→ real Piper voice
→ real speakers

It must not run as part of ./scripts/check.

## Acceptance criteria

- provider-neutral AudioClip exists
- provider-neutral TTSProvider exists
- provider-neutral AudioOutput exists
- Piper provider implements TTSProvider
- local speaker implementation implements AudioOutput
- Piper voice/model is reused
- no runtime voice download
- tests require no hardware/model/network
- ./scripts/check passes
- manual Piper-to-speaker smoke test can be performed separately

## Verification

Run:

    ./scripts/check

## Completion report

Codex must summarize:

- files changed
- architecture implemented
- lifecycle/concurrency decisions
- tests added
- verification results
- any remaining risks or deferred work
