                         COMPANION
                             │
 ┌───────────────────────────┴────────────────────────────┐
 │                                                       │
 │                   SPEECH PIPELINE                     │
 │                                                       │
 │ Microphone                                            │
 │     │                                                 │
 │     ▼                                                 │
 │ AudioSource                                           │
 │     │                                                 │
 │     ▼                                                 │
 │ VADProvider                                           │
 │ Silero                                                │
 │     │                                                 │
 │     ▼                                                 │
 │ STTProvider                                           │
 │ faster-whisper                                        │
 │     │                                                 │
 │     ▼                                                 │
 │ text                                                  │
 │                                                       │
 └───────────────────────┬───────────────────────────────┘
                         │
                         ▼
             ┌────────────────────────┐
             │   AssistantRuntime     │
             │                        │
             │   TurnController       │
             │                        │
             │   ContextBuilder       │
             │       │                │
             │       ├─ Conversation  │
             │       ├─ Memory        │
             │       └─ Tools         │
             │                        │
             │   LLMRouter            │
             └───────────┬────────────┘
                         │
              ┌──────────┼───────────┐
              ▼          ▼           ▼
            Ollama     OpenAI       Other
              │          │           │
              └──────────┼───────────┘
                         │
                         ▼
                   response text
                         │
                         ▼
                   TTSProvider
                         │
                         ▼
                      Speaker
