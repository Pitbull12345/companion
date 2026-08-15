# TASK-0013 — Application Event Contract

## Status
Ready

## Problem

Companion now has a working provider-neutral speech runtime with:

- local and remote LLM providers
- local and remote TTS providers
- character packages
- interactive multi-turn operation
- generic TurnState transitions

A graphical frontend is planned.

The frontend must not depend directly on:

- AssistantRuntime internals
- Ollama
- OpenRouter
- Piper
- ElevenLabs
- PipeWire
- Whisper
- provider-specific types

We need a stable application-level event boundary that a future frontend can
observe.

## Desired outcome

Introduce a provider-neutral Companion application event system.

The runtime/application layer should be able to emit events such as:

- character loaded
- state changed
- transcript ready
- response ready
- speech started
- speech finished
- error
- application stopped

A frontend can subscribe to these events without controlling provider logic.

## Architecture

Desired structure:

    Audio / STT / LLM / TTS
             ↓
       AssistantRuntime
             ↓
      Application events
             ↓
      Event subscriber(s)
        /            \
       CLI         future GUI

The CLI and future GUI should consume the same generic application events where
appropriate.

Do not make the GUI/provider layer directly coupled.

## Event types

Create explicit immutable event value objects.

Prefer a module such as:

    companion.application.events

Suggested event model:

    ApplicationEvent

with concrete dataclasses such as:

    CharacterLoaded
    StateChanged
    TranscriptReady
    ResponseReady
    SpeechStarted
    SpeechFinished
    ApplicationError
    ApplicationStopped

Exact naming may vary if there is a cleaner consistent design.

Events should contain only data needed by application observers.

Do not place concrete provider objects inside events.

## CharacterLoaded

Should expose safe character information required by a future frontend.

At minimum:

- character id
- character name
- available visual asset references if appropriate

Do not expose:

- API keys
- provider clients
- machine configuration secrets

The event may reference CharacterDefinition if doing so remains immutable and
safe, but avoid making the frontend responsible for provider construction.

## StateChanged

Expose generic TurnState transitions.

Examples:

    LISTENING
    TRANSCRIBING
    THINKING
    SPEAKING
    STOPPED

The event must not include provider-specific state.

The same event sequence should occur whether using:

- Ollama or OpenRouter
- Piper or ElevenLabs

## TranscriptReady

Emitted after STT completes.

Contains:

    transcript: str

This allows the future frontend to display what the user said.

Do not require the frontend to inspect STT providers.

## ResponseReady

Emitted after the LLM has produced text.

Contains:

    response: str

This should occur before or at the transition into speech generation as
appropriate.

Do not require the frontend to inspect LLM providers.

## Speech events

Provide provider-neutral events suitable for animation.

At minimum distinguish:

    speech started
    speech finished

These describe application behavior, not provider network calls.

For example:

    SpeechStarted

means Companion is about to audibly speak.

It should not mean:

    ElevenLabs HTTP request started

A frontend should be able to use:

    SpeechStarted -> speaking animation
    SpeechFinished -> idle/listening animation

regardless of TTS implementation.

## Error event

Create a safe application-level error event.

It may include:

- phase/category
- concise public message

It must not expose:

- API keys
- Authorization headers
- raw provider responses containing secrets
- provider client objects
- stack traces as normal event payloads

Existing exception behavior may remain for callers where appropriate.

Do not silently swallow errors merely because an event was emitted.

## Event observer contract

Create a small provider-neutral observer/callback boundary.

Examples:

    ApplicationEventSink
    ApplicationEventObserver
    EventPublisher

or another clear naming scheme.

Prefer a simple protocol such as:

    async def publish(event: ApplicationEvent) -> None

or a synchronous callback if that better matches current runtime behavior.

The architecture must support more than one future consumer without embedding
GUI code into the runtime.

Avoid introducing a heavyweight event framework.

No third-party event-bus dependency.

## Ordering

Event ordering must be deterministic.

A successful turn should conceptually result in something like:

    StateChanged(LISTENING)
    StateChanged(TRANSCRIBING)
    TranscriptReady(...)
    StateChanged(THINKING)
    ResponseReady(...)
    StateChanged(SPEAKING)
    SpeechStarted
    SpeechFinished
    StateChanged(LISTENING)

Exact ordering may vary slightly if required by current semantics, but it must be
documented and tested.

## Existing TurnController

Reuse the existing TurnController / TurnState model where reasonable.

Do not create a second competing state machine.

If TurnController currently supports only one transition callback, refactor
carefully so application events can be produced without breaking existing CLI
behavior.

TurnController remains responsible for valid state transitions.

The event layer reports transitions; it does not redefine their validity.

## AssistantRuntime integration

Emit events at semantic boundaries.

Examples:

after transcription:

    TranscriptReady

after LLM generation:

    ResponseReady

around audible playback:

    SpeechStarted
    SpeechFinished

Do not put provider-specific event emission inside:

- OllamaLLMProvider
- OpenRouterLLMProvider
- PiperTTSProvider
- ElevenLabsTTSProvider

Providers remain adapters.

## Composition

Application composition should create/wire the event publisher/observer.

CharacterApplication should expose the application-level observation seam where
appropriate.

Do not require callers to manually wire events through every provider.

## CLI

Preserve existing CLI behavior.

The CLI may migrate its existing:

    Listening...
    Transcribing...
    Thinking...
    Speaking...

output to consume application events if this improves architecture.

Do not duplicate state reporting through two independent mechanisms.

Existing human-readable terminal behavior should remain equivalent.

## Future frontend requirement

A future GUI should be able to implement logic conceptually like:

    on StateChanged(LISTENING):
        show listening sprite

    on StateChanged(THINKING):
        show thinking sprite

    on SpeechStarted:
        show speaking animation

    on TranscriptReady:
        display user subtitle

    on ResponseReady:
        display companion subtitle

without knowing which model/TTS providers are active.

No actual GUI is implemented in this task.

## Backpressure

Event handling must not create an unbounded queue.

If events are dispatched synchronously, document that observer work must be
small/non-blocking.

If an async queue is used, it must be explicitly bounded and have deterministic
overflow behavior.

Prefer the simplest design that satisfies current requirements.

## Observer failures

An observer/front-end failure must have defined behavior.

Do not allow one bad optional observer to silently corrupt runtime state.

Choose and document one deterministic policy:

- observer failure propagates and stops application
- observer failure is isolated and reported

For this task, prefer explicit propagation unless there is a strong reason to
isolate it.

Do not silently ignore observer exceptions.

## Threading/concurrency

Do not introduce new background threads.

Do not introduce uncontrolled asyncio tasks.

Event order must remain stable.

Cancellation must continue to propagate normally.

Ctrl-C shutdown must remain clean.

## Tests

All tests remain:

- hardware-free
- network-free
- model-free

Add tests for:

- event value objects
- deterministic ordering
- character-loaded event
- state-change events
- transcript event
- response event
- speech-start event
- speech-finished event
- stop event
- safe error event
- no provider objects in event payloads
- no secrets in event repr
- observer exception behavior
- cancellation behavior
- multiple turns
- no duplicate events
- existing TurnController validity remains intact

## Provider-neutral regression tests

Run equivalent fake turns with combinations representing:

    Ollama + Piper
    OpenRouter + Piper
    Ollama + ElevenLabs
    OpenRouter + ElevenLabs

The application event sequence must not depend on provider type.

Fake providers are sufficient.

No real external calls.

## CLI tests

Verify existing terminal output remains correct.

Tests must not require:

- microphone
- speakers
- Ollama
- OpenRouter
- ElevenLabs
- Piper model
- Whisper model
- API keys

## Frontend-oriented integration test

Create a fake event observer that builds a simple frontend state model:

    current_state
    transcript
    response
    speaking

Feed a complete fake turn through the real runtime/application orchestration.

Verify the observer can determine everything above using only application
events.

It must not inspect:

- AssistantRuntime private fields
- provider types
- audio internals

This test represents the future GUI seam.

## Explicit non-goals

Do NOT implement:

- GTK
- Qt
- web frontend
- Electron
- sprite renderer
- animations
- lip sync
- system tray
- window management
- click interactions
- drag interactions
- hotkeys
- provider selection UI
- settings UI
- memory UI
- streaming tokens
- streaming TTS
- WebSockets
- IPC daemon
- DBus
- REST server

## Acceptance criteria

- explicit immutable application event types exist
- events remain provider-neutral
- deterministic turn event ordering exists
- transcript and response events are emitted
- speaking start/finish are observable
- character load is observable
- errors can be represented safely
- frontend can derive visual/application state using events only
- no GUI dependency added
- no provider logic added to frontend-facing event layer
- existing CLI behavior preserved
- cancellation preserved
- cleanup preserved
- tests use no hardware/network/models
- ./scripts/check passes

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed
2. event architecture
3. event types
4. observer/publisher contract
5. event ordering
6. TurnController integration
7. AssistantRuntime changes
8. composition changes
9. CLI changes
10. error behavior
11. cancellation behavior
12. frontend seam
13. tests added
14. verification result
15. architectural deviations
16. deferred GUI work
