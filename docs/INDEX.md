# Companion documentation index

Companion is a local-first, speech-first AI companion.

The primary product path is:

Microphone
→ VAD
→ STT
→ Assistant Runtime
→ LLM
→ TTS
→ Speaker

## Start here

- `ARCHITECTURE.md` — high-level system diagram
- `ROADMAP.md` — milestone sequence

## Architecture

- `architecture/system.md` — component boundaries and dependency direction
- `architecture/speech-pipeline.md` — audio, VAD, STT, and TTS flow
- `architecture/runtime.md` — turn lifecycle and assistant orchestration
- `architecture/providers.md` — replaceable provider contracts
- `architecture/memory.md` — working, semantic, and episodic memory

## Architectural decisions

Individual ADRs under `decisions/` are authoritative.

- `decisions/ADR-001-nix-packaging.md`
- `decisions/ADR-002-provider-boundaries.md`
- `decisions/ADR-003-single-process.md`
- `decisions/ADR-004-memory-ownership.md`

## Tasks

Engineering work is specified under `../tasks/`.

Each task defines:

- the problem being solved;
- relevant architecture;
- required behavior;
- constraints;
- non-goals;
- failure cases;
- acceptance criteria;
- required tests;
- verification commands.

Codex should implement one task at a time.
