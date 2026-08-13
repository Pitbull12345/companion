# ADR-003 — Single process initially

## Status

Accepted

## Decision

The initial Companion application runs VAD, STT, assistant orchestration,
memory, LLM routing, and TTS as components of one application process.

## Why

Separate services would introduce IPC, lifecycle coordination, failure modes,
and packaging complexity before the product requires them.

## Consequences

Component boundaries remain explicit in Python, but they are not network
boundaries.

A future change to multiple processes requires a new ADR.
