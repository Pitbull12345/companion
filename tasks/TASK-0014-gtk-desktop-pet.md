# TASK-0014 — GTK Desktop Pet Frontend

## Status
Ready

## Problem

Companion now has:

- provider-neutral speech runtime
- character packages
- provider registries
- local/remote LLM support
- local/remote TTS support
- deterministic application events
- CharacterLoaded
- StateChanged
- TranscriptReady
- ResponseReady
- SpeechStarted
- SpeechFinished
- ApplicationError
- ApplicationStopped

The application currently has no graphical representation.

We need the first real graphical Companion frontend.

This task should create a small GTK4 desktop-pet window that displays the
character's visual assets and reacts to application events.

This is the first graphical milestone, not the final desktop-pet system.

## Desired outcome

A user can run something conceptually like:

    companion-gui \
      --character ~/.local/share/companion/characters/example \
      --whisper-model ~/.local/share/companion/models/faster-whisper-tiny.en

and see a small graphical character window.

The character should visually react to the existing Companion runtime:

    idle/listening
    transcribing
    thinking
    speaking

The frontend must consume the application event contract introduced in
TASK-0013.

It must not inspect provider implementations.

## Target platform

Primary target for this task:

    Linux
    Fedora
    GNOME
    Wayland
    GTK4

Use GTK4 through PyGObject.

Do not introduce Electron, Qt, a browser frontend, or a web server.

## Architecture

Desired structure:

                 Companion Core
                      |
              Application Events
                      |
                      v
             GtkFrontendObserver
                      |
                      v
              GTK presentation
                      |
                 Character
                   Window

The frontend must not know whether the runtime is using:

- Ollama
- OpenRouter
- Piper
- ElevenLabs
- faster-whisper implementation details
- PipeWire implementation details

It reacts only to application events.

## Frontend package

Prefer a structure similar to:

    companion/frontend/
        __init__.py
        model.py
        gtk.py
        runtime_thread.py

Exact filenames may vary if a cleaner decomposition exists.

Keep GTK-specific code out of the portable runtime/application core.

## Pure frontend model

Create a small GTK-independent presentation model.

For example:

    PetVisualState

with states such as:

    IDLE
    LISTENING
    TRANSCRIBING
    THINKING
    SPEAKING
    ERROR
    STOPPED

This is a frontend presentation concern.

Do not create another runtime TurnState machine.

The model should translate application events into presentation state.

Example mapping:

    CharacterLoaded
        -> load character visual references

    StateChanged(LISTENING)
        -> LISTENING

    StateChanged(TRANSCRIBING)
        -> TRANSCRIBING

    StateChanged(THINKING)
        -> THINKING

    StateChanged(SPEAKING)
        -> do NOT immediately show speaking animation

    SpeechStarted
        -> SPEAKING

    SpeechFinished
        -> leave speaking state

    ApplicationError
        -> ERROR

    ApplicationStopped
        -> STOPPED

Important:

SpeechStarted represents audible speech.

Do not show the speaking visual merely because TTS synthesis has started.

## Character visual keys

Interpret character visual assets using these canonical names:

    idle
    listening
    transcribing
    thinking
    speaking
    error

For this first task:

    idle

is the only required visual.

Other visuals are optional.

Fallback behavior:

    listening     -> listening or idle
    transcribing  -> transcribing or listening or idle
    thinking      -> thinking or idle
    speaking      -> speaking or idle
    error         -> error or idle

Fallback ordering must be deterministic and tested.

Do not silently choose arbitrary assets.

## CharacterLoaded

Use the CharacterLoaded event's safe visual references.

The GTK frontend should not need to access provider composition or private
CharacterApplication internals in order to discover visual assets.

Validate referenced visual files before attempting to display them.

A missing required idle asset should result in a concise frontend error.

Do not crash with a giant traceback during normal CLI usage.

## Image support

For this task support static:

    PNG

images.

Preserve alpha transparency.

Use GTK-supported image/picture facilities.

Do not implement animated GIF handling, sprite sheets, frame sequences, or
video in this task.

Those are later tasks.

## Window

Create a small GTK4 top-level application window.

Requirements:

- borderless / undecorated where supported
- transparent background
- display only the character image
- no traditional application chrome
- no toolbar
- no title bar
- sensible default size
- resize image while preserving aspect ratio
- transparent portions of PNG remain visually transparent

Use Gtk.Application as the application lifecycle owner.

## Wayland constraints

Do not depend on APIs that require absolute global window coordinates.

Do not require:

- exact screen X/Y placement
- restoring exact global coordinates
- forced always-on-top
- X11-only window manipulation
- pointer warping

The first frontend must work within normal GTK4/Wayland constraints.

If interactive window movement is supported through Gdk.Toplevel APIs, it may
be used.

Do not introduce Xlib calls.

## Dragging

Make the pet window user-draggable when practical using GTK/GDK-supported
interactive movement.

Dragging must not mutate core Companion runtime state.

If a reliable portable GTK4 implementation is not possible without
backend-specific hacks, document the limitation rather than introducing X11
code.

## Application/runtime concurrency

GTK owns the main GUI thread.

The existing Companion runtime is asyncio-based.

Integrate them without replacing either architecture.

Prefer:

    main thread
        GTK / GLib main loop

    one explicitly owned worker thread
        asyncio event loop
        CharacterApplication.run()

Do not create arbitrary thread pools.

Do not create one thread per event or one thread per turn.

The runtime worker must have a clear owner and shutdown lifecycle.

## Event delivery across threads

Application events may originate from the runtime worker thread.

GTK widgets must only be mutated from the GTK thread.

Create a frontend observer that safely transfers frontend updates to the GTK
main context, for example using GLib main-context scheduling.

The observer itself should do minimal work.

Do not directly mutate GTK widgets from the runtime thread.

Preserve event order.

## Shutdown

Shutdown behavior is important.

Closing the pet window must stop Companion cleanly.

The frontend must be able to interrupt an active runtime operation rather than
waiting indefinitely for the next completed speech turn.

Use the existing cancellation-safe runtime lifecycle.

Conceptually:

    close GTK window
          |
          v
    request/cancel runtime task
          |
          v
    InteractiveTurnLoop cleanup
          |
          v
    audio/provider resources closed
          |
          v
    runtime thread exits

Do not use os._exit().

Do not leave:

- pw-cat processes
- runtime threads
- asyncio tasks
- HTTP clients
- audio resources

running after GUI shutdown.

Runtime completion or fatal runtime failure should also cause the GTK
application to exit cleanly.

## Runtime failure

ApplicationError should be representable visually.

For this first UI:

- display the error visual if provided
- otherwise fall back to idle
- log/print the concise public error message

Do not display API keys, authorization headers, or raw secret-bearing provider
errors.

Fatal runtime failure should not leave a frozen pet window indefinitely.

## GUI observer

Implement a GTK-facing ApplicationEventObserver.

It should understand:

- CharacterLoaded
- StateChanged
- TranscriptReady
- ResponseReady
- SpeechStarted
- SpeechFinished
- ApplicationError
- ApplicationStopped

TranscriptReady and ResponseReady do not need visible text UI yet.

The observer may retain those values in its frontend model for future work.

Do not add speech bubbles in this task.

## State visuals

Expected visible behavior:

Before first turn:

    idle/listening visual

While user is talking/listening:

    listening visual

While transcription runs:

    transcribing visual if available

While LLM generates:

    thinking visual

During TTS synthesis:

    remain in the appropriate pre-speech visual
    do NOT show speaking merely because TurnState is SPEAKING

When SpeechStarted arrives:

    speaking visual

When SpeechFinished / LISTENING arrives:

    listening visual

On error:

    error visual if available

## CLI entry point

Add a dedicated graphical entry point.

Prefer:

    companion-gui

Do not change the existing:

    companion

CLI into a GUI command.

Existing CLI behavior must continue to work.

The GUI command should reuse the same character/application configuration
logic where practical rather than duplicating provider composition.

At minimum support:

    --character
    --whisper-model

and the same relevant machine/provider configuration currently needed for
character mode:

- Ollama host/timeout
- OpenRouter configuration
- Piper voice root
- ElevenLabs configuration

API keys remain environment variables.

Do not accept API keys directly as command-line arguments.

## Configuration reuse

Avoid copying the entire current CLI parser/configuration implementation if a
small shared application configuration helper can be extracted safely.

Do not perform a large CLI rewrite.

Keep scope focused on GUI launch and configuration reuse.

## GTK dependencies

Add GTK4/PyGObject support correctly to the Nix development and package
environment.

The normal development flow must still work with:

    nix develop

and:

    ./scripts/check

Do not rely on the host Fedora Python environment accidentally providing `gi`.

Nix must provide the GTK/PyGObject dependencies needed by the GUI.

Keep portable core dependencies separated from GUI/platform dependencies where
reasonable.

Do not break the existing non-GUI CLI package.

## Testing strategy

Normal automated tests must remain:

- microphone-free
- speaker-free
- network-free
- model-free
- API-key-free
- display-server-free

Do not require a real Wayland display during ./scripts/check.

Separate testable frontend logic from GTK widget creation.

## Tests

Add deterministic tests for:

- frontend presentation-state model
- visual fallback selection
- CharacterLoaded visual handling
- LISTENING mapping
- TRANSCRIBING mapping
- THINKING mapping
- SpeechStarted mapping to SPEAKING
- StateChanged(SPEAKING) alone does not incorrectly imply audible speech
- SpeechFinished behavior
- error state behavior
- STOPPED behavior
- transcript retention
- response retention
- event ordering through frontend observer boundary
- missing idle asset
- invalid image path
- GUI configuration parsing
- runtime-thread ownership abstraction
- shutdown cancellation request
- worker termination
- runtime failure propagation
- no provider-specific branching

Where GTK itself must be imported, tests must not require opening a real
window.

## Threading tests

Use fake runtime/application objects to prove:

- exactly one owned runtime worker is created
- runtime starts once
- GUI shutdown requests runtime cancellation
- worker exits
- exceptions are captured/reported
- no unbounded tasks are spawned

Do not depend on sleeps for correctness where synchronization primitives can
make the test deterministic.

## Frontend seam test

Build a fake character with visual mappings:

    idle.png
    listening.png
    thinking.png
    speaking.png

Feed application events:

    CharacterLoaded
    StateChanged(LISTENING)
    StateChanged(THINKING)
    StateChanged(SPEAKING)
    SpeechStarted
    SpeechFinished
    StateChanged(LISTENING)

Verify the frontend selects, in order:

    listening.png
    thinking.png
    thinking.png
    speaking.png
    listening.png

The key semantic requirement is:

    StateChanged(SPEAKING)

does not by itself mean audible speech.

## Manual verification

After automated checks pass, document how to create or update a local
character package with:

    [visuals]
    idle = "idle.png"
    listening = "listening.png"
    transcribing = "transcribing.png"
    thinking = "thinking.png"
    speaking = "speaking.png"
    error = "error.png"

Only idle is mandatory.

Provide the exact command needed to launch the GUI with the existing local
character.

## Existing CLI regression

The existing speech-only:

    companion

command must still work exactly as before.

Do not remove its terminal status output.

## Explicit non-goals

Do NOT implement:

- sprite-sheet animation
- frame animation
- animated GIF playback
- lip sync
- mouth phonemes
- speech bubbles
- text chat
- settings panel
- provider-selection UI
- system tray
- autostart
- click-through window
- global hotkeys
- exact persistent screen coordinates
- forced always-on-top
- X11-specific hacks
- DBus daemon
- IPC
- memory UI
- memory implementation
- character editor
- multiple pets
- physics
- walking around desktop
- autonomous movement

## Acceptance criteria

- GTK4/PyGObject frontend exists
- dedicated companion-gui entry point exists
- transparent borderless character window exists
- PNG alpha transparency is preserved
- CharacterLoaded visuals drive the frontend
- visual state reacts to application events
- SpeechStarted controls speaking visual
- frontend remains provider-neutral
- GTK mutations occur on GTK thread
- runtime has one explicitly owned asyncio worker
- clean bidirectional shutdown exists
- existing CLI remains functional
- Nix provides GUI dependencies
- automated tests require no display/hardware/network/models
- ./scripts/check passes

## Verification

Run:

    ./scripts/check

Then perform a real Fedora/Wayland manual diagnostic using a local character
package.

Verify:

1. window appears
2. PNG transparency works
3. window has no normal decorations
4. idle/listening image appears
5. thinking image appears during LLM generation
6. speaking image begins only when audible playback begins
7. image returns to listening after speech
8. window can be closed cleanly
9. runtime thread exits
10. no pw-cat remains

After closing:

    pgrep -a -x pw-cat || echo "no pw-cat processes"

Expected:

    no pw-cat processes

## Completion report

Codex must report:

1. files changed
2. frontend architecture
3. GTK window design
4. event-to-visual mapping
5. visual fallback policy
6. GTK/asyncio integration
7. thread ownership
8. shutdown/cancellation behavior
9. Nix changes
10. CLI changes
11. tests added
12. ./scripts/check result
13. manual verification command
14. Wayland limitations
15. architectural deviations
16. deferred animation work
