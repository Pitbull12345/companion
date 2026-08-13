# Companion agent instructions

Companion is a local-first, speech-first AI companion.

Primary product flow:

Microphone
→ VAD
→ STT
→ Assistant Runtime
→ LLM
→ TTS
→ Speaker

## Workflow

1. Read `docs/INDEX.md`.
2. Read the task file named by the user under `tasks/`.
3. Read only the architecture and decision documents referenced by that task.
4. Inspect existing interfaces and tests before changing code.
5. Implement only the task scope.
6. Add or update required tests.
7. Run `./scripts/check`.
8. Do not claim completion unless required checks pass or you explicitly report what could not be verified.

## Architectural rules

- Core runtime is provider-neutral.
- Runtime depends on interfaces, not concrete Whisper/Ollama/TTS implementations.
- Memory belongs to Companion, not the model.
- Barge-in/cancellation is a first-class runtime requirement.
- OS-specific lifecycle integration stays outside the portable Python core.
- Nix is the primary development and packaging environment.
- Prefer small components, type hints, Protocols, dependency injection, and async boundaries.

## Testing rules

Normal tests must not require:

- microphone hardware
- speaker hardware
- downloaded AI models
- Ollama
- network access
- API keys

Hardware/model-dependent tests belong under `tests/hardware/`.

## Verification

```bash
./scripts/check
