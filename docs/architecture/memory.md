# Memory architecture

Companion owns memory. The LLM does not.

The model receives selected memories through ContextBuilder.

## Working memory

Purpose:

- current conversation;
- recent references;
- follow-up questions.

Initial implementation may be in-memory.

Future persistence will use structured storage.

## Semantic memory

Purpose:

- durable user facts;
- preferences;
- machine/environment knowledge;
- facts where exact occurrence time is not the primary retrieval key.

Example:

    User prefers concise spoken responses.

## Episodic memory

Purpose:

- timestamped activities;
- events;
- questions such as "what was I doing Thursday?"

Example:

    17:32 terminal command `nix develop` in ~/companion

## Long-term storage direction

The intended design is:

    SQLite = authoritative structured record
    vector index = semantic retrieval accelerator

A vector database must not become the sole authoritative memory store.

## Retrieval

ContextBuilder requests only memories relevant to the current turn.

Do not dump all stored memories into the model context.

## Provenance

Persistent memories should eventually retain evidence describing where the
memory came from.

This allows Companion to explain why it believes a remembered fact.

Memory persistence and semantic retrieval are not part of TASK-0001.
