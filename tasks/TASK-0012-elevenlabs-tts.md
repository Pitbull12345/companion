# TASK-0012 — ElevenLabs TTS Provider

## Status
Ready

## Problem

Companion currently supports one real TTS provider:

- Piper

The provider registry/composition system already permits characters to describe:

    [tts]
    provider = "elevenlabs"
    voice = "some-voice-id"

but ElevenLabs is not implemented or registered.

We need a real second TTS provider to prove that character voice selection is
modular in the same way TASK-0011 proved LLM selection is modular.

The implementation must also preserve a clean boundary for the future graphical
Companion frontend.

The frontend must not depend on Piper or ElevenLabs APIs.

## Desired outcome

Implement:

    ElevenLabsTTSProvider

satisfying the existing:

    TTSProvider

contract:

    async def synthesize(text: str) -> AudioClip

Then explicitly register:

    piper
    elevenlabs

in the default TTS registry.

A character should be able to switch from:

    [tts]
    provider = "piper"
    voice = "en_US-lessac-medium"

to:

    [tts]
    provider = "elevenlabs"
    voice = "<voice-id>"

without changing:

- AssistantRuntime
- InteractiveTurnLoop
- AudioOutput
- PipeWire
- STT
- LLM
- conversation handling
- frontend/runtime state interfaces

## Architectural requirement for future frontend

This task must preserve:

CharacterDefinition
        ↓
Application composition
        ↓
TTSProvider
      /     \
  Piper   ElevenLabs
        ↓
     AudioClip
        ↓
    AudioOutput

The future frontend must continue to observe generic application/runtime state.

Do NOT:

- expose ElevenLabs clients to the frontend
- put ElevenLabs-specific state in TurnController
- make SPEAKING state provider-specific
- make CharacterDefinition instantiate providers
- put network calls in GUI code

TurnState.SPEAKING means speaking regardless of TTS provider.

Character visual state remains independent of speech generation implementation.

## Existing contracts

Preserve:

- TTSProvider
- AudioClip
- AudioOutput
- CharacterDefinition
- TTSPreference
- TTSProviderRegistry
- ApplicationConfig
- AssistantRuntime
- InteractiveTurnLoop
- TurnController
- TurnState

Do not redesign TTSProvider merely for ElevenLabs.

The existing boundary remains:

    text
      ↓
    TTSProvider
      ↓
    AudioClip

## ElevenLabs API

Use the ElevenLabs text-to-speech API.

Conceptually:

    POST /v1/text-to-speech/{voice_id}

Authentication uses:

    xi-api-key

The API key must come from machine/user configuration, not character data.

Use non-streaming text-to-speech for this task.

Streaming TTS is deferred.

## HTTP transport

Reuse the project's existing async HTTP dependency (`httpx`) introduced by
TASK-0011 unless there is a strong reason not to.

Do not add the ElevenLabs Python SDK merely to perform one HTTP endpoint if the
existing HTTP abstraction is sufficient.

Use asynchronous network I/O.

Do not block the asyncio event loop.

## Provider module

Prefer:

    src/companion/tts/elevenlabs.py

with a provider conceptually like:

    ElevenLabsTTSProvider(
        voice_id,
        api_key,
        *,
        model_id=...,
        base_url=...,
        timeout=...,
        output_format=...,
        client=None
    )

Exact constructor details may vary to fit the repository.

## Voice identifiers

CharacterDefinition already contains:

    [tts]
    provider = "elevenlabs"
    voice = "voice-id"

Treat `voice` as an opaque ElevenLabs voice identifier.

Do not:

- download a voice
- copy voice recordings into the character package
- store clone samples in CharacterDefinition
- assume whether a voice is premade, designed, professional, or cloned

Any voice ID the user's ElevenLabs account is authorized to use should be
representable without schema changes.

## API key

Use:

    ELEVENLABS_API_KEY

as the preferred environment variable.

The key must NOT be stored in:

- character.toml
- CharacterDefinition
- source code
- tests
- repository configuration
- logs

ApplicationConfig may contain the resolved value with repr disabled.

Do not print the API key.

Do not include xi-api-key headers in error messages.

Do not expose it to a future frontend.

## Application configuration

Extend ApplicationConfig with machine-level ElevenLabs configuration where
appropriate.

At minimum:

- elevenlabs_api_key
- elevenlabs_base_url
- elevenlabs_timeout
- optional default TTS model id
- output format if needed

Keep all of this separate from CharacterDefinition.

Character:

    provider = "elevenlabs"
    voice = "..."

Machine:

    API key
    endpoint
    timeout

## Audio format

Companion's AudioClip represents decoded raw PCM, not MP3 or another encoded
container.

Prefer requesting a raw PCM output format from ElevenLabs so the provider can
construct AudioClip without adding an MP3 decoding dependency.

Use a supported signed 16-bit PCM format.

The provider must know the sample rate implied by the selected output format.

Conceptually:

    ElevenLabs PCM bytes
           ↓
    AudioClip(
        data=...,
        sample_rate=...,
        channels=1,
        sample_width=2
    )

Do not incorrectly label encoded MP3 bytes as AudioClip PCM.

If the selected output format is not one the implementation can safely convert
to AudioClip, reject it clearly.

## Output-format mapping

Implement an explicit bounded mapping between supported ElevenLabs PCM format
identifiers and AudioClip metadata.

Example concept:

    pcm_16000 -> sample_rate 16000
    pcm_22050 -> sample_rate 22050
    pcm_24000 -> sample_rate 24000

Only support formats intentionally tested by this implementation.

Do not infer arbitrary sample rates from unchecked strings.

Do not support MP3, Opus, μ-law, or A-law in this task.

## Request

At minimum send:

- text
- model_id where configured

Voice ID belongs in the request path.

Use:

    xi-api-key: <secret>

Do not implement streaming.

Do not implement speech-to-speech.

## Model selection

The voice ID and TTS model are different concepts.

CharacterDefinition currently stores a logical `voice`.

For this task, the ElevenLabs model may remain machine/application configuration
with a sensible default.

If provider settings are used to allow model_id later, validate them explicitly.

Do not overload CharacterDefinition.voice with model configuration.

## Character TTS settings

TASK-0009 permits simple provider settings.

For ElevenLabs, it is acceptable to support a small explicitly validated set
such as:

- stability
- similarity_boost
- style
- use_speaker_boost
- speed

only if those map cleanly to the current API.

Every supported setting must have explicit validation.

Unknown settings must raise CompositionError.

Do not blindly forward arbitrary settings.

If this substantially expands the task, support no character settings initially
and reject all settings clearly.

## Response handling

Successful synthesis returns binary audio.

Validate:

- non-empty audio bytes
- supported configured PCM format
- expected AudioClip metadata

Return:

    AudioClip

Do not write temporary audio files unnecessarily.

Do not invoke an external media player.

Do not play audio from the provider.

Physical playback remains AudioOutput's responsibility.

## Error handling

Use the existing provider-neutral:

    TTSError

for synthesis/runtime failures.

Translate expected failures including:

- timeout
- connection error
- HTTP 401
- HTTP 403
- HTTP 429
- HTTP 4xx
- HTTP 5xx
- empty response
- malformed/unusable audio response

Examples:

    ElevenLabs request timed out
    ElevenLabs request failed with HTTP 401
    ElevenLabs returned empty audio

Do not include:

- API keys
- authorization headers
- full sensitive response bodies

## Cancellation

Cancellation is first-class.

If synthesize() is cancelled:

- propagate asyncio.CancelledError
- do not convert it to TTSError
- do not retry

This is required so Ctrl-C remains reliable.

## HTTP client lifecycle

Use the same good lifecycle pattern established by OpenRouter.

The owned httpx.AsyncClient should preferably be lazy.

Provider construction must not open an HTTP resource merely by being composed.

Requirements:

- constructor with owned client does not create expensive/open network state
  unnecessarily
- first synthesize() creates the client if needed
- later synthesize() calls reuse it
- close() is async and idempotent
- close() before first synthesis is safe
- provider does not close an externally injected client

Use explicit `client is not None` semantics.

## Provider registration

Extend:

    create_default_tts_registry()

from:

    piper

to:

    piper
    elevenlabs

through explicit registry registration.

Conceptually:

    registry.register("piper", ...)
    registry.register("elevenlabs", ...)

Do not introduce provider if/elif dispatch.

## Composition

Add an ElevenLabs factory at the application composition boundary.

If a character asks for:

    provider = "elevenlabs"

and no API key exists, composition must fail before microphone capture begins.

Expected form:

    Companion configuration error: ELEVENLABS_API_KEY is required for ElevenLabs

A Piper character must not require ELEVENLABS_API_KEY.

There is no automatic Piper fallback.

There is no automatic ElevenLabs fallback.

## Resource ownership

If ElevenLabsTTSProvider owns a closeable HTTP client, application composition
must register it as an owned application resource just as it does for a
closeable LLM provider.

The future structure may therefore be:

InteractiveTurnLoop resources:
    - AudioSource
    - OpenRouter LLM client if used
    - ElevenLabs TTS client if used

Cleanup order must be deterministic.

Normal Ctrl-C must close all owned resources.

No duplicate ownership.

## CLI

Normal character mode remains:

    companion \
      --character /path/to/character \
      --whisper-model /path/to/whisper

For an ElevenLabs character, obtain the secret from:

    ELEVENLABS_API_KEY

Do not require users to put the key directly in a command-line argument.

Machine-level optional CLI settings may include:

    --elevenlabs-base-url
    --elevenlabs-timeout

if useful.

Do not require:

    --piper-model
    --piper-config

for ElevenLabs characters.

## Local-first behavior

Adding ElevenLabs must not make Companion cloud TTS by default.

A Piper character:

    provider = "piper"

must never contact ElevenLabs and must not require an ElevenLabs API key.

An ElevenLabs character:

    provider = "elevenlabs"

may contact ElevenLabs.

There is no automatic cloud fallback.

## Frontend compatibility

This task must deliberately preserve the future GUI seam.

A future frontend should be able to display:

    character.name
    character.visuals["idle"]
    character.visuals["listening"]
    character.visuals["thinking"]
    character.visuals["speaking"]

and respond to generic TurnState changes.

It must not need:

    isinstance(tts, ElevenLabsTTSProvider)

or:

    if provider == "piper"

to determine animation state.

Do not add provider-type checks to state transitions.

No GUI code is required in this task.

## Future frontend event model

Do not build the full event system yet.

However, avoid architectural decisions that prevent a future application
observer from receiving events such as:

    character loaded
    state changed
    transcript completed
    response completed
    speech started
    speech finished
    error

Provider-specific details should remain optional metadata at most, not the
primary UI control mechanism.

## Tests — ElevenLabs provider

Normal tests use an injected fake HTTP client/transport.

No real network calls.

Cover:

- voice ID inserted safely into endpoint
- API key header sent
- text body sent
- configured model ID sent
- configured PCM output format sent
- raw PCM becomes correct AudioClip
- correct sample rate
- mono channel count
- 16-bit sample width
- empty text rejected if appropriate
- empty audio rejected
- 401 translated
- 403 translated
- 429 translated
- 5xx translated
- timeout translated
- connection error translated
- cancellation propagates
- API key absent from repr/errors
- API key absent from error strings
- one owned client reused
- close before use safe
- close idempotent
- injected client not closed

## Tests — output format

Cover every intentionally supported PCM format.

Reject:

- arbitrary output format
- mp3 output
- opus output
- μ-law
- malformed PCM format identifiers

Verify AudioClip metadata exactly matches the output bytes.

## Tests — registry/composition

Cover:

- default TTS registry contains Piper
- default TTS registry contains ElevenLabs
- Piper character remains unchanged
- ElevenLabs character selects ElevenLabs provider
- missing ELEVENLABS_API_KEY fails during composition
- Piper character works without ELEVENLABS_API_KEY
- no fallback occurs
- voice ID originates from CharacterDefinition
- API key originates from ApplicationConfig/environment
- closeable TTS provider becomes an owned resource
- composition failure before runtime does not leak client resources

## Tests — CLI

All CLI tests remain:

- network free
- hardware free
- model free

Cover:

- ElevenLabs character accepted
- ELEVENLABS_API_KEY read from environment
- missing key gives concise configuration error
- API key never printed
- Piper character requires no ElevenLabs key
- optional endpoint/timeout arguments if exposed
- no microphone starts when ElevenLabs configuration fails

## Integration test

Using:

- fake AudioSource
- fake VAD
- fake STT
- fake LLM
- fake/injected ElevenLabs HTTP client
- fake AudioOutput

run at least two turns.

Verify:

- same ElevenLabs provider/client reused
- generic TurnState.SPEAKING is reached
- no provider-specific state is required
- conversation persists
- generated AudioClip reaches AudioOutput
- cleanup closes owned resources exactly once

## Frontend regression test

Add a small architecture-level test proving the runtime state callback remains
provider-neutral.

The same observer should receive equivalent:

    LISTENING
    TRANSCRIBING
    THINKING
    SPEAKING

whether the injected TTS implementation represents Piper or ElevenLabs.

Do not introduce GUI dependencies.

## Real diagnostic

Do not run under ./scripts/check.

Create an ElevenLabs character:

    id = "eleven-test"
    name = "Eleven"

    system_prompt = """
    You are Eleven, a concise desktop voice companion.
    """

    [llm]
    provider = "ollama"
    model = "llama3.2:3b"

    [tts]
    provider = "elevenlabs"
    voice = "<voice-id>"

Set:

    ELEVENLABS_API_KEY

externally.

Run the normal character CLI.

Verify:

1. microphone capture works
2. Whisper works
3. Ollama generates response
4. ElevenLabs produces the character voice
5. AudioOutput plays it normally
6. state still reports SPEAKING generically
7. multiple turns work
8. Ctrl-C cleanly exits
9. no orphan pw-cat processes
10. HTTP client cleanup is correct

Then test an OpenRouter + ElevenLabs character to prove both halves can be
remote simultaneously without runtime changes.

Finally unset ELEVENLABS_API_KEY and confirm a Piper character still works.

## Explicit non-goals

Do NOT implement:

- frontend/GUI
- sprite rendering
- tray application
- desktop window
- lip synchronization
- speech timestamps
- streaming TTS
- WebSocket TTS
- speech-to-speech
- automatic voice cloning
- voice sample upload
- voice creation API
- voice marketplace browsing
- audio asset playback
- sound effects
- provider fallback
- cloud fallback
- automatic retries
- barge-in
- wake word
- memory persistence

## Acceptance criteria

- ElevenLabsTTSProvider implements existing TTSProvider
- returns valid raw PCM AudioClip
- Piper remains unchanged
- ElevenLabs explicitly registered in TTS registry
- voice ID comes from CharacterDefinition
- API key comes from external machine configuration
- character packages contain no secret
- provider client is reused
- cancellation propagates
- owned client is closed
- injected client remains externally owned
- network failures translate to TTSError
- no automatic Piper/ElevenLabs fallback
- Piper characters require no ElevenLabs configuration
- runtime state remains provider-neutral
- future frontend does not need provider-specific logic
- tests require no network/hardware/models
- ./scripts/check passes
- real ElevenLabs speech test succeeds

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed
2. ElevenLabs provider architecture
3. API request shape
4. PCM/output-format strategy
5. AudioClip construction
6. API-key handling
7. client lifecycle
8. cancellation behavior
9. error translation
10. ApplicationConfig changes
11. registry/composition changes
12. CLI/environment behavior
13. frontend compatibility considerations
14. resource ownership
15. tests added
16. verification result
17. real diagnostic instructions
18. architectural deviations
19. deferred frontend/streaming work
