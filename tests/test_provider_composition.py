import asyncio
from pathlib import Path

import pytest

from companion.application import (
    ApplicationConfig,
    CompositionError,
    CompositionFactories,
    LLMProviderRegistry,
    PiperVoiceResolver,
    TTSProviderRegistry,
    compose_character_runtime,
    create_default_llm_registry,
    create_default_tts_registry,
    default_piper_voice_root,
)
from companion.audio.interfaces import AudioClip, AudioFrame, AudioSegment
from companion.character import CharacterDefinition, LLMPreference, TTSPreference
from companion.character import load_character


class FakeLLM:
    def __init__(self) -> None:
        self.messages = []

    async def generate(self, messages):
        self.messages.append(messages)
        return f"answer {len(self.messages)}"


class FakeTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(self, text: str) -> AudioClip:
        self.texts.append(text)
        return AudioClip(b"\0\0", 16_000, 1, 2)


def preference_character(tmp_path: Path) -> CharacterDefinition:
    return CharacterDefinition(
        id="example",
        name="Example",
        system_prompt="Stay in character.",
        package_root=tmp_path,
        llm=LLMPreference("fake-llm", "local-model"),
        tts=TTSPreference("fake-tts", "local-voice"),
    )


def test_registries_are_explicit_local_and_forward_context(tmp_path: Path) -> None:
    config = ApplicationConfig("whisper")
    llm_preference = LLMPreference("custom", "model")
    tts_preference = TTSPreference("custom", "voice")
    received = []
    llm = FakeLLM()
    tts = FakeTTS()
    llm_registry: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    tts_registry: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()
    llm_registry.register("custom", lambda pref, ctx: received.append((pref, ctx)) or llm)
    tts_registry.register("custom", lambda pref, ctx: received.append((pref, ctx)) or tts)

    assert llm_registry.create(llm_preference, config) is llm
    assert tts_registry.create(tts_preference, config) is tts
    assert received == [(llm_preference, config), (tts_preference, config)]

    with pytest.raises(CompositionError, match="already registered"):
        llm_registry.register("custom", lambda pref, ctx: llm)
    with pytest.raises(CompositionError, match="unsupported LLM provider 'missing'"):
        LLMProviderRegistry().create(LLMPreference("missing", "x"), config)
    # A provider string is only a dictionary key; it is never imported.
    with pytest.raises(CompositionError, match="some.module.Class"):
        LLMProviderRegistry().create(
            LLMPreference("some.module.Class", "x"), config
        )
    assert len(create_default_llm_registry()._factories) == 2
    assert len(create_default_tts_registry()._factories) == 2


def test_piper_voice_resolution_is_rooted_and_optional_config(tmp_path: Path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    model = root / "amy.onnx"
    model.write_bytes(b"model")
    resolver = PiperVoiceResolver(root)

    without_config = resolver.resolve("amy")
    assert without_config.model_path == model
    assert without_config.config_path is None
    config = root / "amy.onnx.json"
    config.write_text("{}")
    assert resolver.resolve("amy").config_path == config


@pytest.mark.parametrize("voice", ["../amy", "/tmp/amy", r"C:\\tmp\\amy", "a/b"])
def test_piper_voice_identifier_cannot_escape_root(tmp_path: Path, voice: str) -> None:
    with pytest.raises(CompositionError, match="invalid Piper voice"):
        PiperVoiceResolver(tmp_path).resolve(voice)


def test_piper_voice_resolution_rejects_missing_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    with pytest.raises(CompositionError, match="model not found"):
        PiperVoiceResolver(root).resolve("missing")

    outside = tmp_path / "outside.onnx"
    outside.write_bytes(b"model")
    (root / "unsafe.onnx").symlink_to(outside)
    with pytest.raises(CompositionError, match="escapes"):
        PiperVoiceResolver(root).resolve("unsafe")


def test_default_voice_root_is_home_relative(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert default_piper_voice_root() == (
        tmp_path / ".local/share/companion/voices/piper"
    )


def test_character_composition_reuses_graph_for_two_turns(tmp_path: Path) -> None:
    character = preference_character(tmp_path)
    config = ApplicationConfig("machine-whisper")
    llm = FakeLLM()
    tts = FakeTTS()
    selected = []
    llms: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    ttss: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()
    llms.register("fake-llm", lambda pref, ctx: selected.append((pref, ctx)) or llm)
    ttss.register("fake-tts", lambda pref, ctx: selected.append((pref, ctx)) or tts)

    class Source:
        closed = 0

        async def read_frame(self):
            raise AssertionError("fake VAD does not read source")

        async def close(self):
            self.closed += 1

    class VAD:
        async def capture_utterance(self, source):
            return AudioSegment((AudioFrame(b"\0\0", 16_000, 1, 2),))

    class STT:
        def __init__(self) -> None:
            self.calls = 0

        async def transcribe(self, audio):
            self.calls += 1
            return f"question {self.calls}"

    class Output:
        def __init__(self) -> None:
            self.clips = []

        async def play(self, clip):
            self.clips.append(clip)

    source, stt, output = Source(), STT(), Output()
    completed = []
    application = None

    def on_completed(result):
        completed.append(result)
        if len(completed) == 2:
            application.loop.request_stop()

    application = compose_character_runtime(
        character,
        config,
        llm_registry=llms,
        tts_registry=ttss,
        factories=CompositionFactories(
            audio_source=lambda: source,
            vad=VAD,
            stt=lambda path: stt,
            audio_output=lambda: output,
        ),
        on_turn_completed=on_completed,
    )
    asyncio.run(application.run())

    assert application.character is character
    assert [item[0] for item in selected] == [character.llm, character.tts]
    assert len(llm.messages) == 2
    assert llm.messages[0][0].content == "Stay in character."
    assert llm.messages[1][-2].content == "answer 1"
    assert tts.texts == ["answer 1", "answer 2"]
    assert len(output.clips) == 2
    assert source.closed == 1


def test_character_composition_rejects_missing_preferences(tmp_path: Path) -> None:
    base = dict(
        id="example", name="Example", system_prompt="Prompt", package_root=tmp_path
    )
    with pytest.raises(CompositionError, match="no LLM preference"):
        compose_character_runtime(CharacterDefinition(**base), ApplicationConfig("w"))
    with pytest.raises(CompositionError, match="no TTS preference"):
        compose_character_runtime(
            CharacterDefinition(**base, llm=LLMPreference("ollama", "model")),
            ApplicationConfig("w"),
        )


def test_default_factories_reject_unsupported_settings_before_runtime(tmp_path: Path) -> None:
    character = CharacterDefinition(
        id="example",
        name="Example",
        system_prompt="Prompt",
        package_root=tmp_path,
        llm=LLMPreference("ollama", "model", {"temperature": 0.5}),
        tts=TTSPreference("piper", "voice"),
    )
    with pytest.raises(CompositionError, match="unsupported Ollama"):
        compose_character_runtime(character, ApplicationConfig("w"))


def test_default_registry_selects_openrouter_from_machine_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    provider = FakeLLM()

    def fake_openrouter(model, api_key, **options):
        captured.append((model, api_key, options))
        return provider

    monkeypatch.setattr(
        "companion.application.composition.OpenRouterLLMProvider", fake_openrouter
    )
    config = ApplicationConfig(
        "whisper",
        openrouter_api_key="machine-secret",
        openrouter_base_url="https://router.test",
        openrouter_timeout=18.0,
    )

    selected = create_default_llm_registry().create(
        LLMPreference("openrouter", "vendor/model"), config
    )

    assert selected is provider
    assert captured == [
        (
            "vendor/model",
            "machine-secret",
            {"base_url": "https://router.test", "timeout": 18.0},
        )
    ]
    assert "machine-secret" not in repr(config)


def test_openrouter_requires_key_but_ollama_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ollama = FakeLLM()
    monkeypatch.setattr(
        "companion.application.composition.OllamaLLMProvider",
        lambda model, **options: ollama,
    )
    registry = create_default_llm_registry()
    config = ApplicationConfig("whisper")

    with pytest.raises(CompositionError, match="OPENROUTER_API_KEY is required"):
        registry.create(LLMPreference("openrouter", "vendor/model"), config)
    assert registry.create(LLMPreference("ollama", "local-model"), config) is ollama


def test_openrouter_settings_are_rejected_explicitly() -> None:
    with pytest.raises(CompositionError, match="unsupported OpenRouter"):
        create_default_llm_registry().create(
            LLMPreference("openrouter", "model", {"temperature": 0.5}),
            ApplicationConfig("whisper", openrouter_api_key="key"),
        )


def test_later_composition_failure_does_not_allocate_openrouter_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client_creations = 0

    def create_client(**options):
        nonlocal client_creations
        client_creations += 1
        raise AssertionError("composition must not allocate an HTTP client")

    monkeypatch.setattr(
        "companion.llm.openrouter.httpx.AsyncClient", create_client
    )
    tts_registry: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()

    def fail_later(preference, config):
        raise CompositionError("later TTS composition failure")

    tts_registry.register("failing-tts", fail_later)
    character = CharacterDefinition(
        id="remote",
        name="Remote",
        system_prompt="Prompt",
        package_root=tmp_path,
        llm=LLMPreference("openrouter", "vendor/model"),
        tts=TTSPreference("failing-tts", "voice"),
    )

    with pytest.raises(CompositionError, match="later TTS composition failure"):
        compose_character_runtime(
            character,
            ApplicationConfig("whisper", openrouter_api_key="secret"),
            tts_registry=tts_registry,
        )
    assert client_creations == 0


def test_default_registry_selects_elevenlabs_from_machine_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    provider = FakeTTS()

    def fake_elevenlabs(voice, api_key, **options):
        captured.append((voice, api_key, options))
        return provider

    monkeypatch.setattr(
        "companion.application.composition.ElevenLabsTTSProvider", fake_elevenlabs
    )
    config = ApplicationConfig(
        "whisper",
        elevenlabs_api_key="machine-secret",
        elevenlabs_base_url="https://eleven.test",
        elevenlabs_timeout=14.0,
        elevenlabs_model_id="test-model",
        elevenlabs_output_format="pcm_16000",
    )

    selected = create_default_tts_registry().create(
        TTSPreference("elevenlabs", "character-voice"), config
    )

    assert selected is provider
    assert captured == [
        (
            "character-voice",
            "machine-secret",
            {
                "model_id": "test-model",
                "base_url": "https://eleven.test",
                "timeout": 14.0,
                "output_format": "pcm_16000",
            },
        )
    ]
    assert "machine-secret" not in repr(config)


def test_elevenlabs_requires_key_but_piper_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    piper = FakeTTS()
    monkeypatch.setattr(
        "companion.application.composition.PiperTTSProvider",
        lambda model_path, **options: piper,
    )
    (tmp_path / "voice.onnx").write_bytes(b"model")
    registry = create_default_tts_registry()
    config = ApplicationConfig("whisper", piper_voice_root=tmp_path)

    with pytest.raises(CompositionError, match="ELEVENLABS_API_KEY is required"):
        registry.create(TTSPreference("elevenlabs", "remote-voice"), config)
    assert registry.create(TTSPreference("piper", "voice"), config) is piper


def test_elevenlabs_rejects_settings_and_encoded_output() -> None:
    with pytest.raises(CompositionError, match="unsupported ElevenLabs character"):
        create_default_tts_registry().create(
            TTSPreference("elevenlabs", "voice", {"stability": 0.5}),
            ApplicationConfig("whisper", elevenlabs_api_key="key"),
        )
    with pytest.raises(CompositionError, match="unsupported ElevenLabs PCM"):
        create_default_tts_registry().create(
            TTSPreference("elevenlabs", "voice"),
            ApplicationConfig(
                "whisper",
                elevenlabs_api_key="key",
                elevenlabs_output_format="mp3_44100_128",
            ),
        )


def test_later_composition_failure_does_not_allocate_elevenlabs_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client_creations = 0

    def create_client(**options):
        nonlocal client_creations
        client_creations += 1
        raise AssertionError("composition must not allocate an HTTP client")

    monkeypatch.setattr(
        "companion.tts.elevenlabs.httpx.AsyncClient", create_client
    )
    llm_registry: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    llm_registry.register("fake-llm", lambda preference, config: FakeLLM())
    character = CharacterDefinition(
        id="remote",
        name="Remote",
        system_prompt="Prompt",
        package_root=tmp_path,
        llm=LLMPreference("fake-llm", "model"),
        tts=TTSPreference("elevenlabs", "voice"),
    )
    factories = CompositionFactories(
        audio_source=lambda: (_ for _ in ()).throw(AssertionError("not reached")),
        vad=lambda: (_ for _ in ()).throw(CompositionError("later VAD failure")),
        stt=lambda path: None,
        audio_output=lambda: None,
    )

    with pytest.raises(CompositionError, match="later VAD failure"):
        compose_character_runtime(
            character,
            ApplicationConfig("whisper", elevenlabs_api_key="secret"),
            llm_registry=llm_registry,
            factories=factories,
        )
    assert client_creations == 0


def test_manifest_flows_through_registries_into_composition(tmp_path: Path) -> None:
    package = tmp_path / "character"
    package.mkdir()
    (package / "character.toml").write_text(
        """
id = "example"
name = "Example"
system_prompt = "Manifest personality."

[llm]
provider = "selected-llm"
model = "manifest-model"

[tts]
provider = "selected-tts"
voice = "manifest-voice"
"""
    )
    character = load_character(package)
    llm, tts = FakeLLM(), FakeTTS()
    selections = []
    llms: LLMProviderRegistry[ApplicationConfig] = LLMProviderRegistry()
    ttss: TTSProviderRegistry[ApplicationConfig] = TTSProviderRegistry()
    llms.register("selected-llm", lambda pref, ctx: selections.append(pref) or llm)
    ttss.register("selected-tts", lambda pref, ctx: selections.append(pref) or tts)

    application = compose_character_runtime(
        character,
        ApplicationConfig("independent-whisper"),
        llm_registry=llms,
        tts_registry=ttss,
    )

    assert application.character.system_prompt == "Manifest personality."
    assert selections[0].model == "manifest-model"
    assert selections[1].voice == "manifest-voice"
