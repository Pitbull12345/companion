# System architecture

## Product goal

Companion is a speech-first AI companion designed to support local inference
while allowing replaceable remote providers.

The user should be able to speak naturally and receive a spoken response.

## Primary flow

    Microphone
        │
        ▼
    AudioSource
        │
        ▼
    VADProvider
        │
        ▼
    STTProvider
        │
        ▼
    AssistantRuntime
        │
        ├── TurnController
        ├── ConversationManager
        ├── ContextBuilder
        │      └── MemoryManager
        ├── ToolRegistry
        └── LLMRouter
               │
               ▼
           LLMProvider
               │
               ▼
           TTSProvider
               │
               ▼
            Speaker

## Dependency direction

Core orchestration depends on abstractions.

Concrete providers depend on those abstractions.

For example:

    AssistantRuntime
          │
          ▼
       STTProvider
          ▲
          │
    FasterWhisperSTT

The following dependency is forbidden:

    AssistantRuntime
          │
          ▼
    faster_whisper

The same rule applies to VAD, LLM, TTS, storage, and OS integrations.

## Process model

The initial application runs as one process.

VAD, STT, assistant runtime, memory, LLM routing, and TTS are Python
components within that process.

Do not split components into network services without a future ADR.

## Portability

The portable Python core must not depend on systemd.

Platform lifecycle integration may exist outside the core.

Primary Nix targets are:

- x86_64-linux
- aarch64-linux
- x86_64-darwin
- aarch64-darwin

## Product priorities

In order:

1. correct conversational behavior;
2. low speech latency;
3. cancellation/barge-in;
4. local operation;
5. provider replaceability;
6. durable memory;
7. tools and desktop context.
