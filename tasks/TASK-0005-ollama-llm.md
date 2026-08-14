# TASK-0005 — Ollama LLM Provider

## Status

Done

## Problem

Companion can now:

    microphone
        ↓
    Silero VAD
        ↓
    faster-whisper
        ↓
    user text

The runtime already has a provider-neutral LLMProvider contract:

    class LLMProvider(Protocol):
        async def generate(self, messages: Sequence[Message]) -> str: ...

There is not yet a concrete local LLM implementation.

## Desired outcome

Implement an Ollama-backed LLMProvider that sends Companion's provider-neutral
Message objects to a locally running Ollama server and returns assistant text.

The core runtime must remain unaware of Ollama-specific types.

## System position

    AudioSegment
        ↓
    STTProvider
        ↓
    user text
        ↓
    ContextBuilder
        ↓
    Sequence[Message]
        ↓
    OllamaLLMProvider
        ↓
    Ollama local server
        ↓
    assistant text

This task ends at assistant response text.

## Existing contract

Preserve:

    class LLMProvider(Protocol):
        async def generate(self, messages: Sequence[Message]) -> str: ...

Do not alter AssistantRuntime merely to accommodate Ollama.

## Requirements

Implement OllamaLLMProvider.

It must:

1. accept a configurable model name;
2. accept a configurable Ollama host;
3. default to the normal local Ollama server;
4. convert Companion Message objects into Ollama chat messages;
5. preserve message ordering;
6. correctly map system, user, and assistant roles;
7. use Ollama's asynchronous client path;
8. send one non-streaming chat request for generate();
9. return only the assistant response text;
10. reject malformed or missing response content clearly;
11. wrap provider/network/model failures in a provider-neutral LLM error;
12. remain reusable after a failed request where appropriate.

## Model ownership

The provider does not install, download, pull, create, or delete Ollama models.

Model provisioning is an explicit setup/deployment operation outside this
provider.

If the configured model is unavailable, fail clearly.

Do not automatically call ollama.pull().

## Client boundary

Keep the Ollama client behind a small injectable abstraction so deterministic
tests can use fake clients.

Normal tests must not require:

- an Ollama daemon;
- downloaded models;
- network access;
- API keys;
- microphone hardware.

The concrete implementation may use the official ollama Python package.

## Async behavior

Use Ollama's asynchronous client API.

Do not wrap an asynchronous Ollama request in asyncio.to_thread().

No unbounded background tasks or queues.

generate() cancellation must propagate normally.

Concurrent generate() calls may be supported if the underlying client permits
them; document the chosen behavior.

## Messages

Convert Companion messages into Ollama-compatible chat messages without
changing their semantic content.

Maintain exact ordering.

Do not inject hidden system prompts in this provider.

Prompt construction remains owned by ContextBuilder/runtime.

## Response behavior

Return normalized assistant text.

Do not expose Ollama ChatResponse objects to core runtime.

An empty assistant response should either return an explicitly documented
empty string or fail clearly; choose one behavior and test it.

Do not add streaming to the LLMProvider contract in this task.

## Configuration

At minimum support:

- model name;
- host;
- request timeout if supported cleanly by the client boundary.

Reasonable defaults may be chosen except model selection should remain explicit
unless an existing architecture decision specifies a default.

Do not hard-code a specific model such as llama, gemma, qwen, or mistral into
core runtime.

## Errors

Create a provider-neutral LLM error under the LLM/core error layer.

Clearly surface:

- connection failure;
- unavailable model;
- malformed response;
- other Ollama request failures.

Do not expose raw provider-specific exceptions through LLMProvider when they can
be wrapped meaningfully.

Cancellation must not be converted into an LLM provider error.

## Tests

Use fake Ollama clients.

Test at least:

1. system/user/assistant role mapping;
2. message order preservation;
3. configured model is passed correctly;
4. successful response returns assistant text;
5. empty input message sequence behavior;
6. malformed response failure;
7. connection/request failure wrapping;
8. model-not-found/provider failure wrapping;
9. repeated generate() calls;
10. failure followed by successful reuse;
11. cancellation propagation;
12. implementation satisfies existing LLMProvider contract.

Normal tests must not start Ollama or download a model.

## Integration test

Use:

    Sequence[Message]
        ↓
    OllamaLLMProvider
        ↓
    fake async Ollama client
        ↓
    assistant text

Verify the entire provider boundary without a real daemon.

## Optional real diagnostic

A manual diagnostic may connect to a locally running Ollama daemon and a model
that the developer has explicitly installed.

It must not run during:

    ./scripts/check

## Explicit non-goals

Do not implement:

- model downloading or pulling;
- cloud LLM providers;
- OpenAI;
- Anthropic;
- streaming runtime changes;
- tool calling;
- memory changes;
- TTS;
- speaker output;
- barge-in;
- wake word;
- systemd integration;
- UI.

Do not redesign ContextBuilder or AssistantRuntime.

## Acceptance criteria

TASK-0005 is complete when:

- OllamaLLMProvider satisfies LLMProvider;
- core runtime remains provider-neutral;
- messages are converted correctly;
- Ollama's async request path is used;
- response text is extracted correctly;
- failures are mapped to provider-neutral errors;
- model pulling is never automatic;
- deterministic tests need no Ollama daemon or model;
- all existing tests continue passing;
- ./scripts/check succeeds.

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed;
2. Ollama client integration;
3. message conversion behavior;
4. configuration;
5. async/concurrency behavior;
6. error handling;
7. tests added;
8. ./scripts/check result;
9. architectural deviations;
10. deferred work.
