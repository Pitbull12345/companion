# TASK-0010 — Provider Registry & Character Runtime Composition

## Status
Ready

## Problem

Companion now has:

- provider-neutral runtime contracts
- real PipeWire audio input/output
- Silero VAD
- faster-whisper STT
- Ollama LLM
- Piper TTS
- an interactive multi-turn application loop
- portable CharacterDefinition packages

Character packages can express preferences such as:

    [llm]
    provider = "ollama"
    model = "llama3.2:3b"

    [tts]
    provider = "piper"
    voice = "en_US-lessac-medium"

However, CharacterDefinition is intentionally data-only.

There is currently no application-level composition layer that translates those
provider identifiers into concrete LLMProvider/TTSProvider instances.

The CLI still directly constructs the current provider stack from independent
arguments.

## Desired outcome

Introduce an application composition layer with provider registries/factories
that can translate CharacterDefinition preferences into concrete providers.

Conceptually:

character.toml
      ↓
CharacterLoader
      ↓
CharacterDefinition
      ↓
Application Composition
      │
      ├── LLM registry
      │      "ollama" → Ollama factory
      │
      └── TTS registry
             "piper" → Piper factory
      ↓
AssistantRuntime
      ↓
InteractiveTurnLoop

The architecture must be extensible so later implementations can register:

LLM:
- ollama
- openai
- openrouter
- other local providers

TTS:
- piper
- elevenlabs
- other local/cloud providers

without changing CharacterDefinition or AssistantRuntime.

Only the currently implemented providers should actually be registered in this
task.

## System position

Provider selection belongs in the application/composition layer.

Do NOT place concrete provider construction inside:

- CharacterDefinition
- CharacterLoader
- AssistantRuntime
- InteractiveTurnLoop
- LLMRouter
- TTSProvider interface

Expected separation:

Character package:
    describes preference

Registry/factory:
    translates preference into provider

Application composition:
    combines providers into runtime

AssistantRuntime:
    uses interfaces only

## Existing contracts

Preserve:

- CharacterDefinition
- LLMPreference
- TTSPreference
- LLMProvider
- TTSProvider
- AudioSource
- VADProvider
- STTProvider
- AudioOutput
- AssistantRuntime
- InteractiveTurnLoop
- ConversationManager
- TurnController

Do not redesign these contracts merely to implement provider selection.

## Provider registry

Introduce a small registry/factory abstraction for LLM and TTS providers.

At minimum support:

    llm_registry.create(preference, context)

and:

    tts_registry.create(preference, context)

or an equivalent clean interface.

A registry maps a provider identifier to a construction function/factory.

Conceptually:

    "ollama" -> build_ollama(...)
    "piper"  -> build_piper(...)

Registries must not use large if/elif chains that require modifying central code
for every future provider.

Future provider registration should conceptually be possible through:

    registry.register("openai", ...)
    registry.register("openrouter", ...)
    registry.register("elevenlabs", ...)

Do NOT implement those future providers now.

## Registration

Provider registration must be explicit.

Avoid import-time global side effects where merely importing a module silently
modifies global registries.

Prefer an application composition function such as:

    create_default_llm_registry(...)
    create_default_tts_registry(...)

or equivalent.

The default local application stack should register:

LLM:
- ollama

TTS:
- piper

## Unknown providers

If a CharacterDefinition requests an unregistered provider, fail clearly.

Example:

    provider = "openrouter"

when OpenRouter is not implemented should produce a concise composition error
such as:

    Unsupported LLM provider: openrouter

Do not silently fall back to Ollama.

Likewise:

    provider = "elevenlabs"

must not silently fall back to Piper.

Provider selection must be deterministic and explicit.

## Composition errors

Introduce an application/composition-specific error type, for example:

    CompositionError

or a narrowly scoped hierarchy.

Use it for failures such as:

- unsupported provider identifier
- missing required application configuration
- unable to resolve local voice
- contradictory configuration

Do not expose raw KeyError as the public failure path for registry lookups.

Provider runtime errors should continue using their existing provider-neutral
error contracts.

## LLM composition

Support the existing Ollama provider through the registry.

Character preference:

    [llm]
    provider = "ollama"
    model = "llama3.2:3b"

must result in an OllamaLLMProvider configured with that model.

Application-level configuration may supply values that are not character
identity, such as:

- Ollama host
- timeout

Do not put machine/network-specific Ollama host information into
CharacterDefinition merely for this task.

Provider-specific non-secret character settings may be forwarded where they are
actually supported.

Do not invent unsupported Ollama behavior solely because a settings entry is
present.

Unknown/unsupported settings should either:

- be rejected clearly by the specific factory, or
- remain unused only if that policy is explicitly documented

Prefer explicit rejection over silent ignoring.

## TTS composition

Support the existing Piper provider through the registry.

Character preference:

    [tts]
    provider = "piper"
    voice = "en_US-lessac-medium"

must be capable of resolving that logical voice identifier to the installed
local Piper model.

Character packages must NOT require machine-specific absolute paths.

Do not put:

    /home/device1/...

inside character.toml.

## Piper voice resolution

Introduce an application-level local voice resolution mechanism.

A character contains a logical identifier:

    voice = "en_US-lessac-medium"

Application composition resolves it to local files.

The current conventional installation directory is conceptually:

    ~/.local/share/companion/voices/piper/

For voice:

    en_US-lessac-medium

the resolver may look for:

    en_US-lessac-medium.onnx
    en_US-lessac-medium.onnx.json

The exact root must be configurable and must not hard-code a specific username.

A default may derive from Path.home(), for example a Companion data directory.

Voice resolution belongs to the application/provider composition layer, not the
character package module.

If the required model does not exist, fail clearly before entering the
interactive loop.

Do not download voices automatically.

## Character personality

When composing an application from a CharacterDefinition:

    character.system_prompt

must become the system prompt used by the ContextBuilder.

Do not duplicate the character prompt into provider implementations.

## Character identity lifetime

The loaded CharacterDefinition should remain available to the application
composition result so future UI work can access:

- character id
- display name
- visuals
- sounds

Do not force visual/audio asset support into AssistantRuntime.

## Application configuration

Introduce an application-level configuration object if useful.

It may contain machine/runtime configuration such as:

- Whisper model path
- Ollama host
- Ollama timeout
- Piper voice root
- optional fallback/default provider information

Keep this separate from CharacterDefinition.

The separation should be:

CharacterDefinition:
    who the character is / what it prefers

Application configuration:
    how this machine runs Companion

Examples:

Character:
    ollama
    llama3.2:3b
    piper
    en_US-lessac-medium

Machine:
    Ollama host = localhost
    Piper voices = ~/.local/share/companion/voices/piper
    Whisper model = ~/.local/share/companion/models/faster-whisper-tiny.en

## Runtime composition result

Provide one application-level function/object that can construct the working
local speech stack.

Conceptually:

    compose_character_runtime(character, config)

may produce an object containing:

- CharacterDefinition
- AssistantRuntime
- InteractiveTurnLoop
- owned resources

or equivalent.

Avoid returning an unstructured tuple if a small immutable/application object
would make ownership clearer.

The composition result must preserve existing resource ownership rules.

## Current complete stack

The local character composition path should construct:

PipeWireAudioSource
      ↓
SileroVADProvider
      ↓
FasterWhisperSTTProvider
      ↓
ContextBuilder(character.system_prompt)
      ↓
LLMRegistry
      ↓
configured LLMProvider
      ↓
Piper / configured TTSProvider
      ↓
PipeWireAudioOutput

using:

- one ConversationManager
- one TurnController
- one AssistantRuntime
- one InteractiveTurnLoop

Providers/models must be created once and reused across turns.

## CLI integration

Add an optional supported character-package path.

Preferred interface:

    companion --character /path/to/character ...

The user should be able to run a character without manually repeating:

- system prompt
- Ollama model
- Piper voice model path

Machine-specific arguments such as Whisper model path may still be required or
have application defaults.

Existing explicit CLI behavior should remain available where reasonably
possible.

Do not make character packages mandatory yet.

## CLI precedence

If both character configuration and explicit CLI overrides are supported,
define precedence clearly and test it.

Prefer a simple policy.

For example:

1. explicit CLI override
2. CharacterDefinition preference
3. application default

Do not implement a complicated configuration merging system.

If preserving old CLI options would create ambiguity, fail clearly rather than
silently choosing.

Document the chosen behavior in CLI help/tests.

## Local defaults

Do not hard-code user-specific absolute paths.

Defaults may derive from:

    Path.home()

or a dedicated Companion data-directory helper.

Keep default path construction in the application boundary.

Do not make the core runtime know where models live.

## Provider-specific settings

Character provider settings from TASK-0009 may be made available to the
registered provider factory.

Example:

    [llm.settings]
    temperature = 0.8

However:

- only pass settings the provider actually supports
- reject unsupported settings clearly
- never treat settings as arbitrary **kwargs without validation
- never execute configuration
- never allow secret-bearing character settings

TASK-0009 already rejects secret-like setting keys; preserve that protection.

It is acceptable for the current Ollama/Piper factories to support zero or a
small number of settings if that reflects their existing provider contracts.

Do not expand provider APIs unnecessarily.

## Registry lifecycle

Registries own no provider resources.

They store factory functions/configuration only.

Creating a provider returns ownership to application composition.

No registry close() method should be required.

## Application resource ownership

The composition layer owns resources it creates.

The resulting InteractiveTurnLoop/application must ensure existing shutdown
behavior still closes owned resources such as PipeWireAudioSource.

Do not introduce duplicate ownership where two components both independently
close the same provider.

Respect existing idempotent cleanup behavior.

## Async behavior

Registry lookup and configuration resolution should be synchronous where
possible.

Provider construction may remain synchronous if existing provider constructors
are synchronous/lazy.

Do not start an asyncio event loop in provider factories.

Actual model/network work should retain existing lazy/runtime behavior.

## Cancellation

Do not change existing AssistantRuntime or InteractiveTurnLoop cancellation
semantics.

Composition only constructs the dependency graph.

Ctrl-C must continue to cleanly propagate through the interactive application.

## Security

Provider identifiers are data, not executable module names.

Do NOT:

- dynamically import arbitrary modules from character provider strings
- eval provider names
- execute shell commands
- download code
- load Python modules from character packages

The registry must only construct providers that the application explicitly
registered.

A manifest containing:

    provider = "some.module.Class"

must not cause Python import behavior.

## Failure behavior

Composition failures must happen before the interactive loop starts wherever
possible.

Examples:

- unsupported provider
- missing Piper voice
- missing required application path

must produce clear errors and no partially running Companion loop.

If some resources were already created before a later composition step fails,
ensure they are cleaned up when required.

No failure path may become an indefinite wait.

## Logging / user visibility

CLI errors for composition problems should be concise.

Example:

    Companion configuration error: unsupported TTS provider 'elevenlabs'

Do not print a large traceback for expected user configuration errors.

Unexpected programming errors may continue to fail normally.

## Testing architecture

Normal tests must not construct real:

- microphone streams
- PipeWire subprocesses
- Whisper models
- Ollama clients requiring a daemon
- Piper models
- network requests
- speakers

Factories/composition must support dependency injection so tests can substitute
fake providers/builders.

## Unit tests — registry

Cover:

- register LLM factory
- register TTS factory
- create registered provider
- unknown provider rejected
- duplicate registration policy is deterministic
- provider identifiers are not dynamically imported
- factory receives preference/config context
- no global registry side effects

## Unit tests — Piper voice resolution

Cover:

- logical voice id resolves to model
- optional config resolves
- configurable root
- Path.home-based/default root contains no hard-coded username
- missing model rejected
- absolute/malicious voice identifiers cannot escape voice root
- no automatic downloads
- symlink escape behavior is safe

Voice identifiers must not become arbitrary filesystem paths.

## Unit tests — character composition

Using fake factories/providers verify:

- character system prompt is used
- LLM preference selects correct factory
- TTS preference selects correct factory
- one ConversationManager is created
- one AssistantRuntime is created
- runtime/providers are reused between turns
- CharacterDefinition remains available to application layer
- missing required character preference has deterministic behavior
- unsupported provider fails before running
- resources are cleaned up if composition fails after resource construction

## CLI tests

Normal CLI tests must remain hardware/network/model free.

Cover:

- --character argument
- character package loading
- character system prompt selection
- character LLM model selection
- character TTS voice selection
- machine-level Whisper path remains independent
- Ollama host remains application configuration
- explicit override precedence if implemented
- concise unsupported-provider error
- no traceback for expected configuration errors

## Integration tests

With fully fake providers:

character.toml
      ↓
load_character()
      ↓
provider registries
      ↓
application composition
      ↓
AssistantRuntime
      ↓
InteractiveTurnLoop

Verify at least two turns can execute while:

- the same provider instances are reused
- the same conversation survives
- the character prompt remains active
- cleanup is correct

## Real diagnostic

After automated tests pass, manually create or use a local character package:

    ~/.local/share/companion/characters/example/character.toml

Example:

    id = "example"
    name = "Example"
    system_prompt = "You are Example, a concise local voice assistant."

    [llm]
    provider = "ollama"
    model = "llama3.2:3b"

    [tts]
    provider = "piper"
    voice = "en_US-lessac-medium"

Then start Companion through the character-aware CLI.

Verify:

1. character package loads
2. Ollama model comes from character configuration
3. Piper voice comes from character configuration
4. user does not pass a raw Piper model path
5. character system prompt is active
6. two-turn conversation works
7. Ctrl-C shuts down cleanly
8. no orphan pw-cat process remains

This real diagnostic must not run in ./scripts/check.

## Explicit non-goals

Do NOT implement:

- OpenAI provider
- OpenRouter provider
- ElevenLabs provider
- voice cloning
- provider downloads
- model downloads
- Piper voice downloads
- cloud API authentication
- API key management
- dynamic plugin loading
- character marketplace
- GUI
- sprite rendering
- sound-effect playback
- runtime provider hot-swapping
- provider failover
- model failover
- automatic cloud fallback
- configuration-file framework beyond current character/application needs
- wake word
- barge-in
- memory persistence
- tools/function calling

## Acceptance criteria

- provider registry/factory abstraction exists
- registry does not require central if/elif provider dispatch
- default LLM registry registers Ollama
- default TTS registry registers Piper
- unknown providers fail explicitly
- character package does not instantiate providers
- AssistantRuntime remains provider-neutral
- InteractiveTurnLoop remains provider-neutral
- character system prompt reaches ContextBuilder
- character Ollama model selects Ollama provider/model
- character Piper voice resolves without machine-specific path in manifest
- Piper voice root is application configuration
- no hard-coded /home/device1 path
- provider identifiers never cause dynamic imports
- machine configuration remains separate from character identity
- CLI supports character package startup
- normal tests require no hardware/network/models
- existing explicit CLI behavior remains compatible where practical
- cancellation/cleanup behavior remains intact
- ./scripts/check passes
- real character-driven speech test succeeds

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed
2. provider registry architecture
3. default provider registrations
4. application configuration model
5. character-to-provider composition flow
6. Piper voice resolution behavior
7. CLI changes and precedence rules
8. resource ownership and cleanup
9. security behavior
10. tests added
11. verification result
12. real diagnostic instructions
13. architectural deviations
14. deferred provider work
