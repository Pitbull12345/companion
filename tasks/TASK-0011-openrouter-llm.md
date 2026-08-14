# TASK-0011 — OpenRouter LLM Provider

## Status
Ready

## Problem

Companion currently supports one real LLM provider:

- Ollama

TASK-0010 introduced an explicit provider registry and character-driven
composition system.

Characters can already express:

    [llm]
    provider = "openrouter"
    model = "provider/model"

but OpenRouter is intentionally not registered because no OpenRouter
LLMProvider exists yet.

We now need to implement the first remote/cloud LLM provider and prove that the
provider-neutral architecture can switch a character between:

    Ollama locally

and:

    OpenRouter remotely

without modifying:

- CharacterDefinition
- AssistantRuntime
- InteractiveTurnLoop
- ContextBuilder
- conversation history
- STT
- TTS
- audio input/output

## Desired outcome

Implement:

    OpenRouterLLMProvider

satisfying the existing:

    LLMProvider

contract:

    async def generate(messages: Sequence[Message]) -> str

and register it through the TASK-0010 application registry.

Conceptually:

Character A:

    [llm]
    provider = "ollama"
    model = "llama3.2:3b"

Character B:

    [llm]
    provider = "openrouter"
    model = "some/provider-model"

Both should flow through:

CharacterDefinition
       ↓
LLMProviderRegistry
       ↓
LLMProvider
       ↓
AssistantRuntime

The runtime must not know which one was selected.

## Existing contracts

Preserve the existing:

- Message
- LLMProvider
- LLMError
- LLMRouter
- CharacterDefinition
- LLMPreference
- ProviderRegistry
- ApplicationConfig
- AssistantRuntime
- InteractiveTurnLoop

Do not redesign LLMProvider merely to support OpenRouter.

The existing contract remains:

    async generate(messages) -> str

## OpenRouter transport

Use OpenRouter's chat-completions HTTP API.

The provider should send requests to the configured OpenRouter API base using:

    POST /api/v1/chat/completions

with Bearer authentication.

Do not implement streaming in this task.

Requests should use:

    stream = false

or the equivalent non-streaming behavior.

## HTTP client

Use an async HTTP client.

Prefer adding `httpx` as an explicit project dependency unless the repository
already contains an equally suitable reusable async HTTP abstraction.

Do not use synchronous network I/O on the asyncio event-loop thread.

If httpx is introduced:

- add it to pyproject.toml
- add the corresponding Nix Python dependency
- ensure ./scripts/check verifies/imports it as appropriate

Do not rely on a transitive dependency accidentally making httpx available.

## Provider design

Create a provider such as:

    src/companion/llm/openrouter.py

Conceptual constructor:

    OpenRouterLLMProvider(
        model,
        api_key,
        *,
        base_url=...,
        timeout=...,
        client=None,
        ...
    )

Exact API may vary if a cleaner dependency-injected design fits the repository.

The provider should own or reuse one async HTTP client rather than constructing
a fresh client for every turn.

## API key

The OpenRouter API key is machine/user configuration.

It must NOT be stored in:

- character.toml
- CharacterDefinition
- repository source
- tests
- committed configuration

Support external credential configuration.

Preferred environment variable:

    OPENROUTER_API_KEY

Application configuration may receive the resolved secret, but
CharacterDefinition must never contain it.

Do not print the key.

Do not include the key in exceptions.

Do not log Authorization headers.

## ApplicationConfig

Extend machine-level ApplicationConfig with OpenRouter-specific runtime
configuration where appropriate.

At minimum support:

- API key
- base URL or endpoint root
- timeout

Use sensible provider defaults.

Keep these separate from CharacterDefinition.

Conceptual separation:

CharacterDefinition:

    provider = "openrouter"
    model = "provider/model"

ApplicationConfig:

    api key
    request timeout
    API endpoint

## Character configuration

The existing TASK-0009 schema should require no redesign.

Example:

    [llm]
    provider = "openrouter"
    model = "anthropic/example-model"

The model string is treated as an opaque OpenRouter model identifier.

Do not hard-code a list of allowed model names.

Do not dynamically download or discover models before each request.

## Message mapping

Convert Companion Message objects to OpenRouter chat messages.

Preserve roles:

    system
    user
    assistant

and textual content.

Do not place character-specific logic inside OpenRouterLLMProvider.

The system prompt continues to originate from:

    CharacterDefinition
        ↓
    ContextBuilder
        ↓
    Sequence[Message]

The provider only translates those generic messages into the API request.

## Request body

At minimum include:

- model
- messages

Use non-streaming generation.

Do not implement:

- tools
- function calling
- images
- PDFs
- audio
- reasoning configuration
- structured output
- response formats
- provider-routing customization

unless required for basic text generation.

## Character LLM settings

TASK-0009 supports simple provider settings.

For OpenRouter, support only a small, explicitly validated set if it maps
cleanly to the API.

Good initial candidates:

- temperature
- max_tokens
- top_p

Do not blindly forward arbitrary settings using **kwargs.

Every supported setting must:

- have explicit validation
- have a known expected type/range where practical
- be copied intentionally into the request

Unknown OpenRouter character settings must fail clearly during composition.

If supporting these parameters would unnecessarily expand scope, it is
acceptable to initially support no character settings and reject all of them.

Do not silently ignore unknown settings.

## Response handling

For a successful response:

extract the first assistant textual response from:

    choices[0].message.content

Normalize it consistently with existing Ollama behavior where appropriate.

Reject:

- missing choices
- empty choices
- missing message
- missing content
- non-string content
- empty/whitespace-only assistant text

Raise provider-neutral:

    LLMError

with a concise message.

Do not leak entire raw API responses containing potentially sensitive data into
error messages.

## HTTP failures

Translate expected OpenRouter/network failures into LLMError.

Handle at minimum:

- connection failure
- timeout
- non-success HTTP status
- malformed JSON
- malformed response payload
- authentication failure
- rate limiting
- server error

Preserve useful high-level information such as HTTP status when safe.

Examples:

    OpenRouter request failed with HTTP 401
    OpenRouter request failed with HTTP 429
    OpenRouter request timed out

Do not expose the API key.

Do not retry automatically in this task.

## Cancellation

asyncio cancellation must remain first-class.

If generate() is cancelled while waiting for OpenRouter:

- propagate asyncio.CancelledError
- do not convert cancellation into LLMError
- do not automatically retry

This is necessary so Ctrl-C continues to stop the Companion loop correctly.

## Client lifecycle

Use a reusable HTTP client.

Define ownership clearly.

If the provider constructs its own client, provide an async close mechanism if
required by the HTTP client.

If the provider receives an injected client, avoid incorrectly closing a client
owned by somebody else.

Do not create unbounded clients/connections per turn.

Integrate resource cleanup with application ownership where necessary.

If adding an LLM close contract to the global provider interface would create
unnecessary churn, prefer a provider/application-level resource mechanism.

## Provider registration

Extend:

    create_default_llm_registry()

so it explicitly registers:

    ollama
    openrouter

Conceptually:

    registry.register("ollama", ...)
    registry.register("openrouter", ...)

Do not replace the registry with provider-specific if/elif dispatch.

## Composition

Create an OpenRouter factory at the application composition boundary.

Character:

    provider = "openrouter"
    model = "..."

should select OpenRouterLLMProvider.

Character:

    provider = "ollama"
    model = "..."

must continue selecting OllamaLLMProvider unchanged.

The OpenRouter factory must validate that the API key exists before beginning
the interactive loop.

Example expected error:

    Companion configuration error: OPENROUTER_API_KEY is required for OpenRouter

Do not start microphone capture and fail later on the first turn merely because
the credential was missing.

## CLI

Character mode should continue to work as:

    companion \
      --character /path/to/character \
      --whisper-model /path/to/model

If that character requests OpenRouter, the API key should normally come from:

    OPENROUTER_API_KEY

Avoid requiring the API key directly on the CLI command line because command
arguments may be visible in process listings/shell history.

If an explicit CLI API-key option is added, document the risk and still prefer
environment configuration.

Prefer environment-only secret input for this task.

Optional machine-level CLI configuration may include:

    --openrouter-base-url
    --openrouter-timeout

if useful.

Do not put the model selection on a separate OpenRouter CLI argument in
character mode; it belongs to the character's LLMPreference.

## Security

Do NOT:

- commit API keys
- put API keys in character packages
- print secrets
- include secrets in repr()
- include Authorization headers in errors
- execute model/provider strings
- dynamically import model/provider strings
- shell out to curl
- interpolate model text into executable commands

Provider/model identifiers are data.

## Local-first behavior

Adding OpenRouter must not make Companion cloud-first automatically.

Ollama remains available.

A character using:

    provider = "ollama"

must never contact OpenRouter.

A character using:

    provider = "openrouter"

may contact OpenRouter.

There is no automatic cloud fallback in this task.

## Failure isolation

Importing OpenRouter support must not require:

- an API key
- network access
- an OpenRouter account
- a live request

Normal application startup for an Ollama character must remain unaffected by
missing OpenRouter credentials.

Only composing an OpenRouter character should require OpenRouter configuration.

## Resource ownership

If OpenRouterLLMProvider owns an async HTTP client, ensure it is cleanly closed
when the application exits.

Application composition should own the provider/resources it constructs.

Normal:

    Ctrl-C

must continue to:

- cancel active generation
- close microphone resources
- close HTTP resources if owned
- exit with no traceback

Cleanup must remain idempotent.

## Tests — provider

Use a fake/injected HTTP client or deterministic HTTP transport.

Normal tests must make no real network requests.

Cover:

- Companion message role mapping
- requested model included
- Authorization header construction
- API key not exposed in repr/errors
- assistant text extracted
- whitespace/empty response rejected
- malformed choices rejected
- malformed message rejected
- malformed JSON translated
- HTTP 401 translated
- HTTP 429 translated
- HTTP 5xx translated
- timeout translated
- connection failure translated
- cancellation propagates
- same client reused across generate calls
- no fresh client per turn

## Tests — settings

If OpenRouter settings are supported, test:

- valid temperature
- valid max_tokens
- valid top_p
- unsupported setting rejected
- invalid type rejected
- invalid range rejected

Do not test behavior that the provider does not intentionally support.

## Tests — registry/composition

Cover:

- default registry contains Ollama
- default registry now contains OpenRouter
- OpenRouter character selects OpenRouter factory
- Ollama character remains unchanged
- missing OpenRouter API key fails before interactive run
- OpenRouter config does not affect Ollama characters
- model identifier comes from CharacterDefinition
- API key comes from application/environment configuration
- no fallback occurs from OpenRouter to Ollama
- no dynamic import behavior

## Tests — CLI

All normal CLI tests must remain network/hardware/model free.

Cover:

- OpenRouter character accepted
- API key read from environment
- missing key gives concise configuration error
- secret never printed
- OpenRouter timeout/base configuration if exposed
- Ollama character does not require OPENROUTER_API_KEY
- no real microphone/network starts during configuration-error tests

## Integration test

Using a fake OpenRouter HTTP client plus fake speech providers:

character.toml:

    [llm]
    provider = "openrouter"
    model = "test/model"

        ↓

CharacterLoader
        ↓
provider registry
        ↓
OpenRouterLLMProvider
        ↓
AssistantRuntime
        ↓
InteractiveTurnLoop

Execute at least two fake turns.

Verify:

- same OpenRouter provider/client reused
- conversation context survives
- system prompt survives
- second request includes previous conversation history
- cleanup closes owned HTTP resources once

## Nix/project integration

If adding httpx:

Update:

- pyproject.toml
- flake.nix package dependencies
- flake.nix development environment
- runtime dependency checks where appropriate

Do not rely on httpx existing transitively through another dependency.

`nix develop` and the packaged Nix application must both contain the required
dependency.

## Real diagnostic

Do not run this in ./scripts/check.

After automated tests pass, create a local character package configured with:

    [llm]
    provider = "openrouter"
    model = "<a model available to the user's OpenRouter account>"

    [tts]
    provider = "piper"
    voice = "en_US-lessac-medium"

Set:

    export OPENROUTER_API_KEY='...'

Then run Companion through the normal character CLI.

Verify:

1. character loads
2. OpenRouter provider is selected
3. no Ollama model is needed for that character
4. microphone/VAD/Whisper still work
5. response comes from OpenRouter
6. Piper still produces speech
7. two-turn conversation retains context
8. Ctrl-C shuts down cleanly
9. no orphan pw-cat process
10. HTTP client/resource cleanup is clean

Also verify separately that an Ollama character still works with
OPENROUTER_API_KEY unset.

## Explicit non-goals

Do NOT implement:

- direct OpenAI provider
- Anthropic direct provider
- ElevenLabs
- streaming tokens
- streaming TTS
- streaming STT
- tool/function calling
- image inputs
- PDF inputs
- audio model inputs
- embeddings
- model discovery UI
- automatic model selection
- provider failover
- cloud fallback
- retry policy
- OpenRouter account management
- credit/billing management
- API-key persistence
- OAuth
- secrets manager
- GUI
- sprites
- character audio assets
- memory persistence
- wake word
- barge-in

## Acceptance criteria

- OpenRouterLLMProvider implements existing LLMProvider contract
- no AssistantRuntime changes required for provider-specific behavior
- OpenRouter registered explicitly in LLM registry
- Ollama remains registered and unchanged
- OpenRouter model comes from character preference
- API key comes from external machine/user configuration
- no secrets stored in CharacterDefinition
- no secrets printed/logged
- no dynamic provider imports
- no automatic Ollama/OpenRouter fallback
- async HTTP requests do not block event loop
- cancellation propagates
- network failures become LLMError
- malformed responses become LLMError
- reusable client is used
- owned client is cleanly closed
- tests make no real network requests
- Nix environment contains any new explicit dependency
- ./scripts/check passes
- real OpenRouter speech-to-speech test succeeds
- Ollama character still works afterward

## Verification

Run:

    ./scripts/check

## Completion report

Codex must report:

1. files changed
2. OpenRouter provider architecture
3. HTTP client strategy
4. request/message mapping
5. response parsing
6. error translation
7. cancellation behavior
8. API-key handling
9. ApplicationConfig changes
10. registry/composition changes
11. CLI/environment behavior
12. client/resource ownership
13. dependencies/Nix changes
14. tests added
15. verification result
16. real diagnostic instructions
17. architectural deviations
18. deferred work
