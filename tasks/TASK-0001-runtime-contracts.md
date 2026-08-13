# TASK-0001 — Provider-neutral runtime contracts

## Status

Ready

## Problem

Companion currently has a Nix-packaged Python scaffold but no executable
speech-assistant architecture beyond the CLI placeholder.

Before integrating microphone hardware, Silero, Whisper, an LLM, or TTS, the
project needs stable internal contracts that prove those components can work
together without coupling AssistantRuntime to concrete providers.

Without this layer, every real provider integration could make incompatible
assumptions and force later architectural rewrites.

## Desired outcome

Create the smallest complete, testable logical speech turn:

    Fake AudioSource
          ↓
       Fake VAD
          ↓
       Fake STT
          ↓
    AssistantRuntime
          ↓
    ContextBuilder
          ↓
      LLMRouter
          ↓
       Fake LLM
          ↓
       Fake TTS

A successful automated integration test must execute this entire path without
hardware, models, network access, Ollama, or API credentials.

## Read before implementation

- `AGENTS.md`
- `docs/architecture/system.md`
- `docs/architecture/speech-pipeline.md`
- `docs/architecture/runtime.md`
- `docs/architecture/providers.md`
- `docs/architecture/memory.md`
- `docs/decisions/ADR-002-provider-boundaries.md`
- `docs/decisions/ADR-003-single-process.md`

## Existing state

The repository currently contains:

- Nix packaging;
- `src/companion/`;
- empty subsystem packages for agent, audio, llm, memory, tools, and tts;
- a minimal CLI;
- a basic CLI test.

Do not add real AI/audio provider dependencies in this task.

## Required implementation

### Normalized messages

Create an internal Message representation supporting:

- system
- user
- assistant

Provider-specific message structures must not appear outside adapters.

### Audio contracts

Define:

- AudioFrame
- AudioSegment
- AudioSource
- VADProvider
- STTProvider

Use Python type hints and Protocol interfaces.

Do not import sounddevice, Silero, Whisper, PyTorch, or ONNX Runtime.

### LLM contract

Define LLMProvider.

It accepts normalized Companion messages and asynchronously returns response
text.

### TTS contract

Define TTSProvider.

It asynchronously accepts response text.

### ConversationManager

Implement in-memory working conversation history.

It must:

- store completed user/assistant turns;
- return message history without exposing mutable internal storage;
- support a configurable history limit;
- support clearing current history.

Persistence is out of scope.

### MemoryManager

Create a minimal memory boundary suitable for ContextBuilder.

For TASK-0001 it may return no memories.

Do not implement SQLite, embeddings, or vector search.

### ContextBuilder

Build model context in this order:

1. system prompt;
2. relevant memories if any;
3. previous conversation messages;
4. current user message.

### LLMRouter

Create a minimal router that delegates to an injected LLMProvider.

Multi-provider selection policy is out of scope.

### TurnController

Define at least:

- LISTENING
- TRANSCRIBING
- THINKING
- SPEAKING
- STOPPED

Invalid state transitions must raise a domain-specific error rather than
silently succeeding.

### AssistantRuntime

Implement one asynchronous `run_turn()` operation.

A successful turn must:

1. capture one utterance through VAD;
2. transition to TRANSCRIBING;
3. transcribe it;
4. transition to THINKING;
5. build context;
6. request an LLM response;
7. transition to SPEAKING;
8. speak through TTS;
9. save the completed conversation turn;
10. return to LISTENING;
11. return the transcript and response to the caller.

AssistantRuntime must depend only on Companion interfaces.

## Required module direction

A reasonable layout is:

    src/companion/
      agent/
        messages.py
        conversation.py
        context.py

      audio/
        interfaces.py

      llm/
        interfaces.py
        router.py

      memory/
        manager.py

      runtime/
        __init__.py
        assistant.py
        turn.py

      tts/
        interfaces.py

Codex may make small layout adjustments if needed, but must explain them.

## Explicit non-goals

Do NOT implement:

- microphone capture;
- sounddevice;
- PortAudio integration;
- Silero;
- Whisper;
- faster-whisper;
- Ollama;
- OpenAI;
- Anthropic;
- real TTS;
- SQLite;
- vector search;
- tool calling;
- wake words;
- systemd;
- UI;
- barge-in implementation.

Do not add dependencies for future tasks.

## Acceptance criteria

### Successful voice turn

Given fake audio, VAD, STT, LLM, and TTS providers:

When one runtime turn runs:

Then:

- fake audio flows through the pipeline;
- STT transcript becomes the current user message;
- the system prompt is the first LLM message;
- previous conversation messages appear before the new user message;
- the LLM response reaches TTS;
- the user and assistant messages are stored in conversation history;
- the runtime ends in LISTENING;
- the returned result contains both transcript and response.

### Conversation context

Given a completed previous turn:

When a second context is built:

Then the previous user and assistant messages occur before the new user
message.

### History safety

Calling ConversationManager's history accessor must not allow external code to
mutate its internal list.

### Turn state validation

Given an illegal transition:

When TurnController attempts the transition:

Then a domain-specific transition exception is raised.

## Required tests

Create tests under the appropriate directories.

At minimum cover:

### Unit

- TurnController valid transitions
- TurnController invalid transitions
- ConversationManager stores turns
- ConversationManager history limit
- ConversationManager returned history cannot mutate internal state
- ContextBuilder ordering

### Integration

A complete fake speech-to-speech turn through AssistantRuntime.

The integration test must not use real hardware, models, network access, or
credentials.

Reusable fake providers may live in test support code if that makes the tests
clearer.

## Architectural checks

Tests should make provider boundaries observable.

At minimum, the complete fake integration test must demonstrate that
AssistantRuntime can operate entirely through injected providers.

Do not write brittle tests that merely grep source code unless no behavioral
test can enforce the requirement.

## Verification

Before completion run:

    ./scripts/check

The task is not complete if the normal verification gate fails.

## Completion report

Report:

1. files added or changed;
2. behavior implemented;
3. tests added;
4. exact verification commands and results;
5. architectural deviations, if any;
6. anything intentionally deferred.
