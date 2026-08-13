# ADR-002 — Provider-neutral boundaries

## Status

Accepted

## Decision

AssistantRuntime and other core orchestration components depend on Companion
provider interfaces rather than concrete external implementations.

Concrete VAD, STT, LLM, and TTS implementations are adapters.

## Why

Companion must support local and remote providers without rewriting its core
runtime.

This also makes the entire conversational pipeline testable with deterministic
fake providers.

## Consequences

- provider-specific types stop at adapter boundaries;
- providers are injected rather than constructed by AssistantRuntime;
- tests can replace every external provider;
- adding a new provider should not require changing orchestration logic.
