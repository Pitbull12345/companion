# TASK-0009 — Character Package Foundation

## Status
Ready

## Problem

Companion now has a working multi-turn speech runtime with provider-neutral
boundaries for:

- audio input
- VAD
- STT
- LLM
- TTS
- audio output

The current CLI still receives personality, Ollama model, Piper voice, and other
runtime configuration independently.

There is no first-class representation of a Companion character.

Future characters need to package identity and preferences such as:

- display name
- personality/system prompt
- preferred LLM provider/model
- preferred TTS provider/voice
- visual assets
- character sound assets

without coupling the character definition to concrete runtime implementations.

## Desired outcome

Introduce a provider-neutral CharacterDefinition and character package loader.

A character package should conceptually look like:

character/
├── character.toml
├── visuals/
│   ├── idle.png
│   ├── listening.png
│   ├── thinking.png
│   └── speaking.png
└── sounds/
    ├── startup.wav
    ├── laugh.wav
    └── confused.wav

The manifest should describe the character but must not directly construct
runtime providers.

Conceptually:

CharacterDefinition
├── identity
├── personality
├── LLM preference
├── TTS preference
├── visual asset references
└── sound asset references

Later application composition can use this definition to select concrete
providers.

## System position

Character configuration sits above provider implementations and below the
application composition layer.

Conceptually:

character.toml
      ↓
CharacterLoader
      ↓
CharacterDefinition
      ↓
Application composition
      ↓
┌──────────────┬──────────────┐
│              │              │
LLM factory    TTS factory    visual runtime
│              │
LLMProvider    TTSProvider
│              │
└────── AssistantRuntime ─────┘

CharacterDefinition must not import or instantiate:

- OllamaLLMProvider
- PiperTTSProvider
- ElevenLabs
- OpenAI
- OpenRouter
- PipeWire
- GUI frameworks

## Existing contracts

Preserve the existing provider-neutral architecture.

Character configuration may express a preference for a provider, model, or
voice, but provider construction remains outside the character package.

Do not modify the core LLMProvider, TTSProvider, AudioSource, AudioOutput, STT,
or VAD contracts merely to support character configuration.

## Character identity

Define an immutable character data model containing at minimum:

- stable character id
- display name
- system prompt/personality
- optional description

Example:

    id = "zara"
    name = "Zara"
    description = "Local-first desktop companion"

The stable id should be suitable for filenames/configuration references.

Validate character ids using a conservative format such as lowercase
letters, numbers, hyphens, and underscores.

## LLM preference

A character may optionally express a preferred LLM configuration.

The configuration must remain provider-neutral.

At minimum support:

- provider identifier
- model identifier

Example:

    [llm]
    provider = "ollama"
    model = "llama3.2:3b"

Future examples should be representable without schema redesign:

    [llm]
    provider = "openai"
    model = "gpt-example"

or:

    [llm]
    provider = "openrouter"
    model = "provider/model"

Do NOT implement those providers in this task.

The character definition represents preference/configuration only.

## TTS / character voice preference

A character may optionally express its preferred TTS provider and voice.

At minimum support:

- provider identifier
- voice/model identifier

Examples:

    [tts]
    provider = "piper"
    voice = "en_US-lessac-medium"

Future configuration must also be capable of representing:

    [tts]
    provider = "elevenlabs"
    voice = "voice-id"

Do NOT implement ElevenLabs in this task.

Do not store API keys or other secrets inside character packages.

Secrets must remain external to character data.

## Provider-specific settings

Allow a small provider-neutral mechanism for optional provider-specific
non-secret settings.

For example:

    [llm.settings]
    temperature = 0.8

or:

    [tts.settings]
    speed = 1.0

Keep this bounded to simple TOML scalar values.

Do not allow arbitrary executable configuration.

Do not interpret provider-specific settings inside the character package
module.

The application/provider factory may interpret them in a future task.

## Audio input is not character voice

Do not make microphone selection part of the character's TTS voice.

Character voice means generated speech output.

Microphone/input selection belongs to application/device configuration and
remains independent from character identity.

A future user should be able to use the same character with:

- default PipeWire microphone
- another microphone
- another AudioSource

without changing the character package.

## Visual assets

Support optional named visual asset references.

At minimum allow states such as:

- idle
- listening
- transcribing
- thinking
- speaking

Do not require every state to exist.

The schema should remain extensible for future animation states.

Example:

    [visuals]
    idle = "visuals/idle.png"
    listening = "visuals/listening.png"
    thinking = "visuals/thinking.png"
    speaking = "visuals/speaking.png"

Do NOT load image pixels or implement GUI behavior.

This task only resolves and validates asset references.

## Character sound assets

Support optional named audio asset references such as:

- startup
- greeting
- laugh
- confused

Example:

    [sounds]
    startup = "sounds/startup.wav"
    laugh = "sounds/laugh.wav"

Do not decode or play these assets in this task.

Do not restrict the schema to only those names; future character-specific
events should be representable.

## Manifest format

Use TOML for the initial character manifest.

Use Python's standard TOML parser where available rather than introducing an
unnecessary parsing dependency.

Expected filename:

    character.toml

Example:

    id = "example"
    name = "Example"
    description = "Example Companion character"

    system_prompt = """
    You are Example, a concise desktop companion.
    """

    [llm]
    provider = "ollama"
    model = "llama3.2:3b"

    [tts]
    provider = "piper"
    voice = "en_US-lessac-medium"

    [visuals]
    idle = "visuals/idle.png"
    listening = "visuals/listening.png"
    thinking = "visuals/thinking.png"
    speaking = "visuals/speaking.png"

    [sounds]
    startup = "sounds/startup.wav"
    laugh = "sounds/laugh.wav"

## Paths and portability

Asset paths in character.toml must be relative to the character package
directory.

Do not store machine-specific absolute paths such as:

    /home/device1/...

Resolve asset references relative to the package root.

Reject path traversal that escapes the character package directory.

Examples that must be rejected:

    ../../secret
    /etc/passwd

Character packages must be relocatable.

Moving:

    ~/characters/example/

to another directory should not require editing character.toml.

## Loader

Implement a CharacterLoader or equivalent function that loads:

    <package-directory>/character.toml

and returns an immutable CharacterDefinition.

The loader must:

- parse TOML
- validate required fields
- validate types
- normalize package-relative asset paths
- reject paths escaping the package root
- report malformed configuration using a character-specific exception
- not instantiate runtime providers
- not open image/audio asset contents

The loader may optionally validate that referenced files exist.

If existence validation is implemented, behavior must be deterministic and
documented.

## Errors

Introduce provider-neutral character/package errors such as:

    CharacterError

or a small hierarchy if justified.

Errors should clearly identify issues such as:

- manifest missing
- malformed TOML
- missing required field
- invalid character id
- invalid provider configuration
- invalid asset path
- unsupported value type

Do not expose raw KeyError/TypeError/TOML parser errors as the normal API.

## Immutability

CharacterDefinition and nested configuration objects should preferably be
immutable dataclasses or equivalent immutable structures.

Loading a character must not create shared mutable provider settings between
characters.

## Lifecycle and ownership

CharacterDefinition owns no external resources.

Loading a character:

- opens the manifest
- parses it
- closes the file immediately
- returns immutable data

No subprocesses, model handles, network clients, or background tasks belong in
this module.

No explicit close() method should be required.

## Concurrency and async behavior

Character loading is local filesystem configuration work and does not require
asyncio.

Do not introduce background tasks or threads.

Provider initialization remains outside this task.

## Buffering and backpressure

Not applicable.

Character packages do not produce streaming data or queues.

## Resource limits

Loading must be bounded by the size of one manifest and its metadata.

Do not recursively load arbitrary package directory contents.

Do not preload visual or sound files into memory.

## Failure behavior

Manifest or validation failures are immediate and deterministic.

A failed load returns no partially initialized CharacterDefinition.

No failure may result in a retry loop or indefinite wait.

## CLI/application integration

Do not replace the existing CLI configuration system completely in this task.

Provide enough integration that later application composition can accept a
CharacterDefinition.

It is acceptable to add an optional character-loading boundary or helper, but
do not implement provider factories in this task.

Existing explicit CLI model/voice configuration should continue working unless
a narrowly scoped compatibility change is required.

## Security

Character packages are data, not code.

Do not:

- execute Python from character packages
- dynamically import modules named by the manifest
- execute shell commands
- allow environment-variable expansion that could expose secrets
- read files outside the package through asset references
- store API keys in the package

Provider names are identifiers only.

## Example character fixture

Add a small example/test character package containing:

- character.toml
- placeholder or test visual references where necessary
- placeholder or test sound references where necessary

Do not add large binary assets to the repository merely for testing.

## Explicit non-goals

Do NOT implement:

- ElevenLabs API integration
- voice cloning
- OpenAI LLM provider
- OpenRouter LLM provider
- new Ollama behavior
- provider factories
- provider switching at runtime
- GUI
- sprite rendering
- animation
- audio asset playback
- image decoding
- audio decoding
- wake word
- microphone selection
- barge-in
- memory persistence
- downloadable character marketplace
- remote character packages
- automatic asset downloads
- API-key storage
- executable plugins

## Tests

### Unit tests

Add deterministic tests for:

- valid manifest loading
- required identity fields
- system prompt
- optional description
- LLM provider/model preference
- TTS provider/voice preference
- provider settings
- visual references
- sound references
- immutable returned configuration
- repeated loads do not share mutable state

### Validation tests

Cover:

- missing character.toml
- malformed TOML
- missing id
- missing name
- missing system prompt
- invalid character id
- malformed LLM section
- malformed TTS section
- invalid settings value
- absolute asset path
- parent-directory traversal
- asset path escaping package root
- malformed visuals/sounds tables

### Portability tests

Construct temporary character directories and verify:

- relative paths resolve from package root
- package may move to another root
- no user-specific absolute path is required

### Security tests

Verify manifests cannot cause:

- Python execution
- shell execution
- arbitrary imports
- reading assets outside the package root

Normal tests must require:

- no microphone
- no speaker
- no AI model
- no Ollama
- no PipeWire
- no network
- no API key
- no GUI

## Acceptance criteria

- immutable CharacterDefinition exists
- TOML character packages load successfully
- personality/system prompt is represented
- optional LLM provider/model preference is represented
- optional TTS provider/voice preference is represented
- future provider identifiers such as openai/openrouter/elevenlabs do not
  require changing the core CharacterDefinition schema
- visual asset references are represented
- sound asset references are represented
- character packages contain no secrets
- asset paths are portable and package-relative
- package traversal is rejected
- character module imports no concrete runtime providers
- no provider is instantiated by loading a character
- tests require no hardware/network/models
- ./scripts/check passes

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed
2. character data model
3. TOML schema
4. loader behavior
5. validation/security behavior
6. path-resolution behavior
7. extensibility for future LLM/TTS providers
8. tests added
9. verification result
10. architectural deviations
11. deferred work
