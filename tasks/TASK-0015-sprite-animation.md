# TASK-0015 — Sprite / Frame Animation System

## Status
Ready

## Problem

TASK-0014 introduced the first GTK desktop-pet frontend.

The frontend can currently display static PNG assets for presentation states such
as:

- idle
- listening
- transcribing
- thinking
- speaking
- error

The next milestone is to make the character visibly animate.

We need a deterministic, character-package-driven frame animation system that
supports simple looping sprite animation without coupling animation behavior to
LLM, TTS, STT, or audio providers.

This task should make the desktop pet feel alive while preserving the existing
provider-neutral application/event architecture.

## Desired outcome

A character package may define animated frame sequences for presentation states.

For example:

    idle/
        000.png
        001.png
        002.png
        003.png

    thinking/
        000.png
        001.png
        002.png

    speaking/
        000.png
        001.png
        002.png
        003.png

When the frontend enters a presentation state:

    IDLE
    LISTENING
    TRANSCRIBING
    THINKING
    SPEAKING
    ERROR

the GTK frontend should automatically play the corresponding frame sequence.

Example:

    listening
        ↓
    listening animation loop

    StateChanged(THINKING)
        ↓
    thinking animation loop

    StateChanged(SPEAKING)
        ↓
    retain thinking animation

    SpeechStarted
        ↓
    speaking animation loop

    SpeechFinished
        ↓
    listening animation loop

No provider-specific knowledge should be required.

## Architecture

Desired structure:

            Application Events
                   |
                   v
          Presentation Model
                   |
                   v
          Animation Controller
                   |
                   v
           Frame Sequence
                   |
                   v
             GTK Picture

Keep animation as a frontend/presentation concern.

Do not put animation logic into:

- AssistantRuntime
- TurnController
- CharacterApplication
- Ollama provider
- OpenRouter provider
- Piper provider
- ElevenLabs provider
- STT provider
- audio source/output

## Design principles

The animation layer should be:

- provider-neutral
- event-driven
- deterministic
- testable without GTK
- testable without a display server
- independent of real time where practical
- independent of hardware
- independent of network access
- character-package-driven

Do not introduce a game engine.

Do not introduce a heavyweight animation framework.

## Character package animation format

Extend character visual metadata in a minimal, explicit way.

Prefer supporting animation definitions in character.toml.

A suggested format is:

    [visuals]
    idle = "idle.png"

    [animations.idle]
    frames = [
        "animations/idle/000.png",
        "animations/idle/001.png",
        "animations/idle/002.png",
        "animations/idle/003.png",
    ]
    fps = 6
    loop = true

    [animations.listening]
    frames = [
        "animations/listening/000.png",
        "animations/listening/001.png",
    ]
    fps = 4
    loop = true

    [animations.thinking]
    frames = [
        "animations/thinking/000.png",
        "animations/thinking/001.png",
        "animations/thinking/002.png",
    ]
    fps = 5
    loop = true

    [animations.speaking]
    frames = [
        "animations/speaking/000.png",
        "animations/speaking/001.png",
        "animations/speaking/002.png",
        "animations/speaking/003.png",
    ]
    fps = 8
    loop = true

Exact representation may vary if there is a cleaner design, but it must remain:

- declarative
- portable
- relative to the character package
- easy for users to edit manually
- safe against path traversal

Do not require one TOML file per animation.

## Character model

Add a provider-neutral immutable animation definition.

Suggested concept:

    AnimationDefinition

Fields may include:

    frames: tuple[Path, ...]
    fps: float
    loop: bool

CharacterDefinition may expose:

    animations: Mapping[str, AnimationDefinition]

or an equivalent immutable structure.

Do not store GTK objects in CharacterDefinition.

Do not store loaded Gdk.Texture objects in CharacterDefinition.

CharacterDefinition remains portable data.

## Animation keys

Use the same canonical presentation keys introduced by TASK-0014:

    idle
    listening
    transcribing
    thinking
    speaking
    error

Animation keys must not depend on runtime providers.

## Static visual compatibility

Existing character packages using only:

    [visuals]

must continue to work.

Animations are optional.

A character must not be forced to define animations.

The frontend should support:

    animation available
        → animate frames

    no animation available
        → use static visual fallback from TASK-0014

Do not break existing static visual packages.

## Fallback policy

Animation fallback must be deterministic.

For a requested presentation state, prefer:

1. animation for that exact state
2. static visual for that exact state
3. existing TASK-0014 visual fallback chain

Examples:

### LISTENING

Prefer:

    animations.listening

otherwise:

    visuals.listening

otherwise:

    animations.idle if supported by the design

otherwise:

    visuals.idle

### TRANSCRIBING

Prefer:

    animations.transcribing
    visuals.transcribing
    animations.listening
    visuals.listening
    animations.idle
    visuals.idle

### THINKING

Prefer:

    animations.thinking
    visuals.thinking
    animations.idle
    visuals.idle

### SPEAKING

Prefer:

    animations.speaking
    visuals.speaking
    animations.idle
    visuals.idle

### ERROR

Prefer:

    animations.error
    visuals.error
    animations.idle
    visuals.idle

Do not silently pick arbitrary animations.

Document and test the exact precedence.

## Frame validation

Every animation frame must:

- exist
- be a regular file
- remain inside the character package
- have .png extension
- have a valid PNG signature

Reject:

- empty frame lists
- missing frame files
- directory paths
- path traversal
- symlink escape if existing package validation already protects against this
- unsupported extensions
- invalid PNG files

Failures should result in concise CharacterError/frontend configuration errors.

Do not defer malformed animation definitions until halfway through rendering if
they can be rejected at character load time.

## FPS validation

Animation FPS must be finite and positive.

Reject:

    fps <= 0
    NaN
    infinity

Use a sensible supported upper bound to prevent pathological schedules.

For example:

    0 < fps <= 60

or another clearly documented bound.

Do not silently clamp invalid values.

## Loop behavior

Support:

    loop = true
    loop = false

For looping animations:

    last frame
        ↓
    first frame

For non-looping animations:

    last frame remains displayed

Do not automatically return to another application state merely because a
non-looping animation finishes.

Application events remain the source of state changes.

## Default loop behavior

If loop is omitted, choose and document one default.

Prefer:

    loop = true

because presentation-state animations are usually loops.

## Timing model

Create a GTK-independent animation controller/model.

It should be possible to test frame advancement without real sleeps.

Suggested responsibilities:

    activate animation
    current frame index
    current frame path
    advance one frame/tick
    loop handling
    non-loop terminal handling
    reset when animation changes

Keep wall-clock scheduling separate from animation state logic.

## GTK scheduling

GTK remains the GUI thread owner.

Use GTK/GLib-supported timers for frame scheduling.

Examples include a GLib timeout/source or another GTK-native scheduling
mechanism.

Do not use:

- one Python thread per animation
- asyncio sleep loops on the GTK thread
- arbitrary background animation threads
- busy loops

Only the existing Companion runtime worker should remain a background thread.

Animation frame advancement belongs on the GTK thread.

## Timer lifecycle

Only one active animation timer should exist for the pet window.

When presentation state changes:

    cancel/remove old animation timer
    reset animation
    install new timer if needed

Avoid accumulating GLib timer sources.

Closing the window must remove the active animation source.

No timers should fire after GTK widget destruction.

## Event semantics

Preserve TASK-0014 semantics.

### StateChanged(LISTENING)

Activate listening animation/static visual.

### StateChanged(TRANSCRIBING)

Activate transcribing animation/static visual.

### StateChanged(THINKING)

Activate thinking animation/static visual.

### StateChanged(SPEAKING)

Do not activate speaking animation yet.

Retain the previous pre-speech visual.

This is important because TurnState.SPEAKING includes TTS synthesis time.

### SpeechStarted

Activate speaking animation/static visual.

### SpeechFinished

Return to listening animation/static visual.

### ApplicationError

Activate error animation/static visual.

### ApplicationStopped

Stop active animation timer and transition to stopped/idle presentation as
defined by the existing frontend model.

Do not change runtime state semantics.

## Speaking animation

Speaking animation is not lip sync.

It may be a generic:

- talking motion
- head bob
- mouth-open / mouth-closed cycle
- body movement

Do not attempt phoneme timing in this task.

The only speech synchronization point is:

    SpeechStarted
    SpeechFinished

## State transition behavior

When switching animations, always reset to frame 0.

Example:

    thinking frame 2
        ↓
    SpeechStarted
        ↓
    speaking frame 0

If the same state event is received redundantly, avoid unnecessary timer churn
where practical.

Do not allow stale timers from a previous state to advance the new animation.

## Texture/image loading

Avoid repeatedly decoding PNG files every frame if a simple safe cache can
improve behavior.

A frontend-only texture cache is acceptable.

Requirements:

- cache belongs to GTK/frontend layer
- character model retains only paths
- no provider/runtime coupling
- deterministic invalidation is not required for files edited while application
  is running

A simple per-window or per-character texture cache is sufficient.

Do not implement a global asset manager framework.

## Memory/resource bounds

Animation frame caching must remain bounded by the active character package.

Do not create an unbounded cache keyed by arbitrary paths/events.

For this task it is acceptable to load each declared animation frame once for
the active character.

## CharacterLoaded

When CharacterLoaded arrives:

- load safe static visual references
- load safe animation definitions through the frontend/package model
- prepare the active character visual resources

If animation definitions are already present in CharacterDefinition but are not
included in CharacterLoaded, extend CharacterLoaded only with safe portable
animation metadata if necessary.

Do not expose:

- provider objects
- API keys
- runtime internals

Prefer a minimal safe event contract extension.

If CharacterLoaded can remain unchanged and frontend composition can safely
provide animation metadata through another existing character-facing seam,
document that architecture.

Do not make GTK inspect private runtime fields.

## Event contract compatibility

Do not break existing TASK-0013 observers.

Any extension to CharacterLoaded must preserve compatibility where practical.

Avoid changing unrelated event types.

Do not add animation-specific events to the runtime.

The runtime should not emit:

    AnimationFrameChanged
    IdleAnimationStarted
    SpeakingFrameAdvanced

Those are frontend concerns.

## GUI configuration

No new required command-line arguments should be necessary for normal
animation use.

Animations belong to character packages.

Do not add:

    --idle-fps
    --speaking-fps
    --animation-directory

unless a compelling architectural requirement exists.

Character TOML should define animation behavior.

## Manual package example

Support a character package structure conceptually like:

    my-character/
        character.toml

        visuals/
            idle.png
            listening.png
            thinking.png
            speaking.png

        animations/
            idle/
                000.png
                001.png
                002.png

            thinking/
                000.png
                001.png
                002.png
                003.png

            speaking/
                000.png
                001.png
                002.png
                003.png

## Testing

All automated tests must remain:

- display-free
- microphone-free
- speaker-free
- network-free
- model-free
- API-key-free

Do not require a live GTK window during ./scripts/check.

## Character loader tests

Add tests for:

- valid animation parsing
- multiple animation states
- default loop behavior
- explicit non-looping animation
- valid FPS
- zero FPS rejected
- negative FPS rejected
- excessive FPS rejected
- NaN/infinity rejected if representable through configuration
- empty frames rejected
- missing frame rejected
- non-PNG frame rejected
- invalid PNG rejected
- traversal rejected
- symlink escape rejected where applicable
- immutable animation mappings
- existing visuals-only package remains valid

## Animation model tests

Add deterministic unit tests for:

- first frame selected on activation
- frame increment
- looping sequence wraps
- non-looping animation stops at final frame
- animation change resets frame index
- static fallback does not create animation ticking
- same-state activation behavior
- no stale frame advancement after state change

Tests should not use real sleeps.

## Presentation integration tests

Feed:

    CharacterLoaded
    StateChanged(LISTENING)
    StateChanged(THINKING)
    StateChanged(SPEAKING)
    SpeechStarted
    SpeechFinished
    StateChanged(LISTENING)

Verify:

    listening animation
    thinking animation
    thinking animation remains
    speaking animation
    listening animation

Specifically verify:

    StateChanged(SPEAKING)

does not activate the speaking sequence.

## GTK adapter tests

Test GTK-facing scheduling logic through fakes where possible.

Verify:

- one timer installed
- old timer removed on animation change
- timer removed for static image
- timer removed at shutdown
- timer callback advances frame
- texture selection corresponds to animation frame
- destroyed/stopped frontend does not continue scheduling

Do not require a real display.

## Regression tests

Existing static image behavior from TASK-0014 must still work.

Existing:

    companion

CLI must remain unchanged.

Existing:

    companion-gui

must work with characters that have no animation definitions.

No provider-specific branches may appear in frontend animation code.

## Performance

This is simple sprite animation.

Do not prematurely optimize.

However:

- do not decode PNG bytes on every timer tick
- do not create a thread per frame
- do not allocate an ever-growing history of frames
- do not emit runtime events for every animation frame

## Error behavior

Malformed animation configuration should fail clearly during character loading
or frontend initialization.

Runtime provider errors should still use existing ApplicationError behavior.

Do not convert provider failures into animation errors.

If an optional animation fails but a valid deterministic static fallback exists,
choose one explicit policy and test it.

Prefer strict package validation at load time rather than silently accepting
broken declared assets.

## Nix/package changes

Add no new heavy GUI framework.

GTK4/PyGObject already exists from TASK-0014.

Only modify dependencies if genuinely necessary.

./scripts/check must continue validating packaged/Nix behavior.

## Manual diagnostic

After automated tests pass, provide a manual test using the existing local
ElevenLabs character.

Create at least:

    animations/idle
    animations/thinking
    animations/speaking

with several PNG frames.

Launch:

    nix develop -c env PYTHONPATH=src python -m companion.frontend.cli \
      --character "$HOME/.local/share/companion/characters/eleven-test" \
      --whisper-model "$HOME/.local/share/companion/models/faster-whisper-tiny.en"

Verify:

1. idle/listening visibly loops
2. thinking visibly loops while LLM generation occurs
3. StateChanged(SPEAKING) does not immediately switch to speaking frames
4. speaking animation begins when audible speech begins
5. speaking frames continue during playback
6. listening/idle animation resumes after speech finishes
7. no duplicate/stale animation timers are visible
8. window closes cleanly
9. Ctrl-C closes cleanly
10. runtime thread exits
11. no pw-cat remains

After shutdown:

    pgrep -a -x pw-cat || echo "no pw-cat processes"

Expected:

    no pw-cat processes

## Explicit non-goals

Do NOT implement:

- lip sync
- phoneme detection
- visemes
- audio amplitude-driven mouth movement
- sprite sheets
- GIF decoding
- APNG
- WebP animation
- video
- skeletal animation
- tweening framework
- physics
- autonomous movement
- walking around the desktop
- mouse-following behavior
- blinking driven by random timers
- emotes
- speech bubbles
- text chat
- multiple characters
- settings UI
- animation editor
- hot reload
- character marketplace
- always-on-top hacks
- X11-specific behavior

## Acceptance criteria

- character packages can declare frame animations
- animation configuration is immutable and validated
- existing visuals-only characters remain compatible
- frontend supports animated and static states
- deterministic fallback exists
- animation controller is GTK-independent
- GTK owns frame scheduling
- only one active animation timer exists
- state changes reset frame sequence appropriately
- looping animations wrap correctly
- non-looping animations stop correctly
- StateChanged(SPEAKING) does not start speaking animation
- SpeechStarted starts speaking animation
- SpeechFinished returns to listening
- PNGs are not re-decoded every frame
- no provider-specific animation logic exists
- no new background animation threads exist
- shutdown removes timers
- existing CLI remains unchanged
- existing GUI remains compatible
- tests require no display/hardware/network/models
- ./scripts/check passes
- real Fedora/Wayland animation diagnostic succeeds

## Verification

Run:

    ./scripts/check

Then run the real GUI diagnostic.

## Completion report

Codex must report:

1. files changed
2. animation architecture
3. character animation schema
4. AnimationDefinition model
5. validation rules
6. fallback precedence
7. animation controller behavior
8. GTK timer implementation
9. texture/frame caching
10. event-to-animation mapping
11. speaking semantics
12. shutdown/timer cleanup
13. backward compatibility
14. tests added
15. ./scripts/check result
16. manual diagnostic setup
17. manual diagnostic command
18. architectural deviations
19. deferred lip-sync work
