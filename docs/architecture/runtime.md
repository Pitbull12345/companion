# Assistant runtime

## Responsibility

AssistantRuntime orchestrates one conversational turn.

It must not contain implementation-specific AI or audio logic.

## Turn lifecycle

Normal flow:

    LISTENING
        ↓
    TRANSCRIBING
        ↓
    THINKING
        ↓
    SPEAKING
        ↓
    LISTENING

The TurnController owns these states.

## One turn

A successful turn performs:

1. VAD captures one utterance.
2. STT converts it to text.
3. Turn state becomes THINKING.
4. ContextBuilder assembles model context.
5. LLMRouter requests a response.
6. Turn state becomes SPEAKING.
7. TTS speaks the response.
8. ConversationManager stores the completed turn.
9. State returns to LISTENING.

## Context assembly

The intended context ordering is:

    system instructions
    relevant long-term memory
    working conversation history
    current user message

Future tool information may also be included.

The LLM should receive selected context, not direct access to the entire
persistent memory store.

## Conversation ownership

ConversationManager owns current conversational history.

The first implementation may be in-memory.

Persistence will be introduced separately so that runtime contracts do not
depend on a database implementation.

## Failure behavior

Component exceptions should remain visible to callers.

Runtime code must not silently swallow provider failures.

The runtime should leave itself in a recoverable state when practical.

Detailed cancellation and recovery semantics may be expanded in later tasks.

## Barge-in

Barge-in is a core requirement but is not part of the first runtime-contract
implementation.

The initial interfaces must not prevent later cancellation support.
