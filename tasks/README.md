# Companion task workflow

Each implementation task should be small enough for one bounded Codex pass.

## Required task sections

### Problem
What concrete problem exists today?

### Desired outcome
What should be true when the task is complete?

### System position
Where does this component sit in the architecture?

### Existing contracts
Which interfaces, data models, and architectural rules must be preserved?

### Requirements
What behavior must be implemented?

### Lifecycle and ownership
Define, where applicable:

- who creates the component;
- when resources are acquired;
- when resources are released;
- repeated startup/shutdown behavior;
- ownership of external resources.

If not applicable, state that explicitly.

### Concurrency and async behavior
Define, where applicable:

- asyncio boundaries;
- thread boundaries;
- blocking operations;
- cancellation behavior;
- event-loop ownership.

### Buffering and backpressure
For producers/consumers, define:

- queue or buffer limits;
- overflow behavior;
- stale-data policy;
- ordering guarantees.

### Resource limits
Consider bounded growth of:

- memory;
- queues;
- files;
- connections;
- threads;
- subprocesses.

### Failure behavior
Define:

- initialization failures;
- runtime failures;
- failed-state behavior;
- retry/recovery expectations;
- whether subsequent calls fail, recover, or block.

No fatal failure should silently turn into an indefinite wait.

### Explicit non-goals
State what later tasks must not be implemented.

### Tests

#### Unit tests
Fast tests of isolated behavior.

#### Contract tests
Verify implementations satisfy provider-neutral contracts.

#### Integration tests
Verify components interact correctly using fakes.

#### Long-running/system scenarios
Where applicable, test situations such as:

- producer faster than consumer;
- repeated calls;
- resource cleanup;
- failure followed by another operation;
- cancellation;
- prolonged idle periods.

Normal tests must not require:

- microphone hardware;
- speaker hardware;
- downloaded AI models;
- Ollama;
- network access;
- API keys.

Hardware/model tests belong outside the normal verification gate.

### Acceptance criteria
List mechanically verifiable completion conditions.

### Verification

Run:

    ./scripts/check

The task is not complete unless required checks pass.

### Completion report

Codex must report:

1. files changed;
2. behavior implemented;
3. dependency changes;
4. lifecycle/concurrency behavior;
5. tests added;
6. verification command and result;
7. architectural deviations;
8. deferred work.

## Development loop

    Architecture
        ↓
    Task specification
        ↓
    Acceptance/failure scenarios
        ↓
    Task branch
        ↓
    Codex implementation
        ↓
    ./scripts/check
        ↓
    Human architecture review
        ↓
    focused correction if needed
        ↓
    PR
        ↓
    merge
        ↓
    update roadmap/task status

Task definitions and workflow/harness changes should be committed to `main`
before creating the implementation branch.
