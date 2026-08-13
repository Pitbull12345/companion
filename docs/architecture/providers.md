# Provider architecture

## Purpose

External implementations are replaceable adapters behind stable Companion
interfaces.

## Initial provider boundaries

### AudioSource

Produces microphone audio frames.

Expected operation:

    async read_frame() -> AudioFrame

### VADProvider

Collects one spoken utterance from an AudioSource.

Expected operation:

    async capture_utterance(source: AudioSource) -> AudioSegment

### STTProvider

Converts speech audio into text.

Expected operation:

    async transcribe(audio: AudioSegment) -> str

### LLMProvider

Generates an assistant response from normalized Companion messages.

Expected operation:

    async generate(messages) -> str

### TTSProvider

Speaks assistant text.

Expected operation:

    async speak(text: str) -> None

## Provider-neutral messages

LLM providers must consume Companion's internal message representation rather
than leaking OpenAI, Ollama, Anthropic, or other provider-specific structures
into the runtime.

Initial roles:

- system
- user
- assistant

## Dependency injection

Concrete providers are supplied to runtime components.

Example:

    runtime = AssistantRuntime(
        stt=my_stt_provider,
        llm=my_llm_provider,
        tts=my_tts_provider,
        ...
    )

Runtime code must not instantiate concrete providers internally.

## Testing

Every provider boundary must be usable with a fake implementation.

Normal automated tests may not require:

- physical audio hardware;
- model downloads;
- Ollama;
- network access;
- API credentials.

Real-provider tests belong in integration or hardware-specific suites as the
project evolves.
