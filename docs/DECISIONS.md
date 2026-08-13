ADR-001 — Nix packaging

Decision:
Nix is the primary development and packaging environment.

Reason:
We need reproducible environments across Linux and macOS.


ADR-002 — Provider-neutral runtime

Decision:
AssistantRuntime cannot depend directly on concrete STT,
LLM, VAD, or TTS implementations.

Reason:
Providers must be replaceable.


ADR-003 — Single process initially

Decision:
VAD, STT, runtime, memory and TTS operate within one
Companion process initially.

Reason:
Separate services add complexity without current benefit.


ADR-004 — Speech-first

Decision:
Speech is the primary user interface.

Text interfaces exist primarily for tests and diagnostics.


ADR-005 — Memory ownership

Decision:
Companion manages persistent memory.

LLMs receive retrieved memory as context and are not the
authoritative memory store.
