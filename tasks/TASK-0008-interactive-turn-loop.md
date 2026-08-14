# TASK-0008 — Interactive Turn Loop

## Status
Ready

## Problem

Companion can now complete one real speech-to-speech turn:

Microphone
→ PipeWireAudioSource
→ Silero VAD
→ faster-whisper STT
→ AssistantRuntime
→ Ollama
→ Piper TTS
→ PipeWireAudioOutput

The complete pipeline has been validated on real Fedora hardware.

However, Companion currently requires one-off Python scripts to run a single turn.
After responding once, the process exits.

There is no application-level loop that repeatedly listens, processes a turn,
speaks the response, and returns to listening.

## Desired outcome

Provide a reusable interactive runtime loop that continuously executes
AssistantRuntime turns until explicitly stopped.

Desired user behavior:

Companion starts
    ↓
Listening
    ↓
user speaks
    ↓
Companion responds
    ↓
Listening again
    ↓
user speaks again
    ↓
Companion responds
    ↓
...
Ctrl-C / stop request
    ↓
clean shutdown

The loop must preserve conversation history between completed turns.

## System position

The interactive loop sits above AssistantRuntime.

It coordinates application lifetime but does not implement VAD, STT, LLM, TTS,
audio input, or audio output itself.

Conceptually:

Application / CLI
        ↓
InteractiveTurnLoop
        ↓
AssistantRuntime.run_turn()
        ↓
existing provider-neutral pipeline

AssistantRuntime remains responsible for one logical turn.

## Existing contracts

Preserve:

- AssistantRuntime
- TurnController
- TurnState
- AudioSource
- VADProvider
- STTProvider
- LLMRouter
- TTSProvider
- AudioOutput
- ConversationManager

Do not move provider-specific behavior into the loop.

The loop must depend on the runtime abstraction, not directly on PipeWire,
Silero, Whisper, Ollama, or Piper.

## Requirements

### Repeated turns

Implement an application-level component that repeatedly invokes:

    await runtime.run_turn()

After a successful turn, it must immediately begin another listening cycle.

Completed turns must retain the existing ConversationManager history.

The runtime/providers should be reused across turns rather than reconstructed
after every response.

### Turn visibility

The loop must expose enough state/events for the CLI to show useful progress.

At minimum the interactive CLI should be able to indicate:

- Listening
- recognized user transcript
- assistant response

Do not require provider-specific logging.

Avoid hiding long operations such that the user cannot distinguish listening,
transcription, model inference, or completion where existing runtime state can
provide that information.

### Stop behavior

The loop must support explicit graceful stopping.

Ctrl-C / asyncio cancellation must:

- stop the active loop
- cleanly release owned application resources
- not start another turn
- not produce an unnecessary traceback during normal user shutdown

A normal Ctrl-C should be treated as user-requested shutdown.

### Runtime failures

A fatal turn failure must not silently become an infinite wait.

For this task, use a simple fail-fast policy:

- report the error
- stop the interactive loop
- clean up resources

Do not add automatic retries or restart policies yet.

### CLI integration

Add a supported CLI path that starts the interactive Companion.

The user must not need to paste a Python script.

Prefer integrating this with the existing `companion` CLI rather than adding a
separate unrelated executable unless the current CLI architecture strongly
requires otherwise.

The CLI should assemble the current real local stack:

PipeWireAudioSource
SileroVADProvider
FasterWhisperSTTProvider
OllamaLLMProvider
PiperTTSProvider
PipeWireAudioOutput

Configuration values such as model and voice paths must not be scattered
through the runtime loop itself.

Keep construction/configuration at the application/CLI composition boundary.

### Configuration

For this task, support explicit configuration through CLI arguments and/or
well-defined defaults for:

- Whisper model path
- Ollama model
- Ollama host if already supported
- Piper model path
- Piper config path
- system prompt

Do not introduce a full configuration-file framework yet.

Do not hard-code user-specific `/home/device1/...` paths in reusable source
code.

Defaults may derive from the current user's home directory where appropriate.

### Resource ownership

The application composition layer owns resources it creates.

At minimum, ensure PipeWireAudioSource is closed when the loop exits.

If another provider gains an explicit close/shutdown contract, respect it.

Cleanup must occur on:

- normal stop
- Ctrl-C
- cancellation
- runtime failure

Cleanup must be idempotent where underlying components already support
idempotent close.

### Lifecycle

Startup:

1. construct providers once
2. construct ConversationManager once
3. construct AssistantRuntime once
4. start interactive loop

Per turn:

1. LISTENING
2. capture utterance
3. TRANSCRIBING
4. build transcript
5. THINKING
6. generate response
7. SPEAKING
8. play response
9. return to LISTENING

Shutdown:

1. stop accepting new turns
2. cancel/finish active operation according to existing cancellation contracts
3. close owned AudioSource
4. exit cleanly

### Concurrency and async behavior

The interactive loop must run within one asyncio event loop.

Do not create one asyncio event loop per turn.

Do not create permanent background tasks unless required.

Turns are sequential for this task:

    listen → think → speak → listen

Do not listen for the next utterance while TTS is playing.

Barge-in is explicitly deferred.

### Cancellation

Cancellation is a first-class requirement.

Cancellation during:

- VAD capture
- STT
- LLM generation
- TTS synthesis
- playback

must propagate through existing provider contracts and cause the interactive
application to shut down cleanly.

Do not swallow asyncio.CancelledError inside the interactive loop.

Normal CLI Ctrl-C should not print a large traceback.

### Buffering and backpressure

The interactive loop introduces no new audio queues.

Existing provider buffering behavior remains authoritative.

The loop must not accumulate completed TurnResult objects indefinitely.

Only conversation history managed by ConversationManager may persist according
to its configured history limit.

### Resource limits

The loop must not introduce unbounded growth in:

- tasks
- subprocesses
- threads
- audio buffers
- TurnResult objects
- logs

Provider/model instances should be reused.

Conversation history remains bounded by ConversationManager.

### Failure behavior

Initialization failure:

- fail clearly before entering the interactive loop
- clean up any resources already constructed if needed

Turn failure:

- report the failure
- stop the loop
- clean up
- do not silently retry

Shutdown failure:

- report a concise error
- do not hang indefinitely

No failure path may turn into an indefinite wait.

## Explicit non-goals

Do NOT implement:

- barge-in
- simultaneous listening and speaking
- wake word
- character packages
- sprites or GUI
- ElevenLabs
- imported sound effects
- memory persistence
- episodic recall
- tools/function calling
- cloud LLM routing
- automatic provider failover
- automatic restart/retry
- daemon/systemd service installation
- configuration-file framework
- hot model switching
- streaming LLM tokens
- streaming TTS
- streaming STT

## Tests

### Unit tests

Add deterministic tests for the loop using fake runtime/resources.

Cover:

- repeated successful turns
- runtime instance reused
- loop stops when requested
- no additional turn begins after stop
- completed results do not accumulate unboundedly
- turn failure stops loop
- cancellation propagates
- cleanup occurs exactly as required
- cleanup remains safe when invoked after failure

### Contract tests

Verify the loop depends on a runtime-compatible abstraction rather than concrete
PipeWire/Ollama/Piper classes.

### Integration tests

Using fake providers/runtime:

- simulate multiple sequential speech turns
- confirm conversation survives between turns
- confirm state returns to LISTENING after each successful turn
- confirm failure prevents another turn
- confirm cancellation shuts down cleanly

### CLI tests

Normal tests must not start:

- PipeWire
- microphones
- speakers
- Whisper models
- Ollama
- Piper models
- network requests

Inject factories/configuration so CLI composition and shutdown can be tested
without real providers.

Verify argument parsing for relevant model/provider configuration.

### Long-running/system scenarios

Test a bounded simulation of many turns and verify:

- no task accumulation
- no result accumulation
- runtime reused
- cleanup happens once
- conversation limit remains bounded

## Real diagnostic

After normal tests pass, manually validate on Fedora:

1. start Companion through the supported CLI
2. speak a question
3. hear the spoken response
4. wait for Companion to listen again
5. speak a second question
6. verify conversation context is retained
7. press Ctrl-C while listening
8. verify immediate clean shutdown with no traceback
9. verify no orphan pw-cat processes remain

This hardware/model test must not run under `./scripts/check`.

## Acceptance criteria

- interactive application performs multiple turns
- one AssistantRuntime instance is reused
- providers/models are reused across turns
- ConversationManager persists across turns
- CLI starts the real local speech stack
- no user-specific absolute paths are hard-coded
- Ctrl-C exits cleanly
- cancellation propagates
- runtime failure stops the loop
- owned AudioSource is always closed
- no unbounded result/task growth
- normal tests need no hardware/models/Ollama/network
- `./scripts/check` passes
- real two-turn Fedora speech test succeeds

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed
2. loop/application architecture
3. CLI behavior and arguments
4. resource ownership
5. cancellation and Ctrl-C behavior
6. failure policy
7. provider/model reuse behavior
8. tests added
9. verification result
10. real diagnostic instructions
11. deferred work
