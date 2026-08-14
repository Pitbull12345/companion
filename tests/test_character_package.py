import dataclasses
import shutil
from pathlib import Path

import pytest

from companion.character import (
    CharacterDefinition,
    CharacterError,
    CharacterLoader,
    load_character,
)


FIXTURE = Path(__file__).parent / "fixtures" / "characters" / "example"


def write_manifest(root: Path, content: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "character.toml").write_text(content, encoding="utf-8")
    return root


def minimal_manifest(**replacements: str) -> str:
    fields = {
        "id": 'id = "test_character"',
        "name": 'name = "Test Character"',
        "system_prompt": 'system_prompt = "Be helpful."',
    }
    fields.update(replacements)
    return "\n".join(fields.values())


def test_loads_complete_example_character_definition() -> None:
    character = load_character(FIXTURE)

    assert isinstance(character, CharacterDefinition)
    assert character.id == "example"
    assert character.name == "Example"
    assert character.description == "Example local-first Companion character"
    assert character.system_prompt == "You are Example, a concise desktop companion."
    assert character.package_root == FIXTURE.resolve()
    assert character.llm is not None
    assert character.llm.provider == "ollama"
    assert character.llm.model == "llama3.2:3b"
    assert character.llm.settings == {"temperature": 0.8}
    assert character.tts is not None
    assert character.tts.provider == "piper"
    assert character.tts.voice == "en_US-lessac-medium"
    assert character.tts.settings == {"speed": 1.0}
    assert character.visuals["idle"] == (FIXTURE / "visuals/idle.png").resolve()
    assert character.visuals["listening"] == (
        FIXTURE / "visuals/listening.png"
    ).resolve()
    assert character.sounds["startup"] == (
        FIXTURE / "sounds/startup.wav"
    ).resolve()


def test_optional_sections_and_description_may_be_absent(tmp_path: Path) -> None:
    character = CharacterLoader().load(
        write_manifest(tmp_path / "minimal", minimal_manifest())
    )

    assert character.description is None
    assert character.llm is None
    assert character.tts is None
    assert character.visuals == {}
    assert character.sounds == {}


def test_definition_and_nested_mappings_are_immutable() -> None:
    character = load_character(FIXTURE)

    with pytest.raises(dataclasses.FrozenInstanceError):
        character.name = "Changed"  # type: ignore[misc]
    assert character.llm is not None
    with pytest.raises(TypeError):
        character.llm.settings["temperature"] = 0.1  # type: ignore[index]
    with pytest.raises(TypeError):
        character.visuals["idle"] = Path("changed")  # type: ignore[index]


def test_repeated_loads_share_no_mutable_configuration() -> None:
    first = load_character(FIXTURE)
    second = load_character(FIXTURE)

    assert first == second
    assert first is not second
    assert first.llm is not None and second.llm is not None
    assert first.llm.settings is not second.llm.settings
    assert first.visuals is not second.visuals
    assert first.sounds is not second.sounds


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ('name = "Missing id"\nsystem_prompt = "Prompt"', "requires.*id"),
        ('id = "missing-name"\nsystem_prompt = "Prompt"', "requires.*name"),
        ('id = "missing-prompt"\nname = "Missing Prompt"', "requires.*system_prompt"),
        (
            minimal_manifest(id='id = "Invalid Character!"'),
            "invalid character id",
        ),
        (minimal_manifest(name="name = 3"), "requires.*name"),
        (minimal_manifest(system_prompt='system_prompt = ""'), "requires.*system_prompt"),
    ],
)
def test_required_identity_validation(
    tmp_path: Path, manifest: str, message: str
) -> None:
    with pytest.raises(CharacterError, match=message):
        load_character(write_manifest(tmp_path / "character", manifest))


def test_missing_and_malformed_manifest_are_character_errors(tmp_path: Path) -> None:
    with pytest.raises(CharacterError, match="manifest not found") as missing:
        load_character(tmp_path / "missing")
    assert isinstance(missing.value.__cause__, FileNotFoundError)

    package = write_manifest(tmp_path / "malformed", "id = [")
    with pytest.raises(CharacterError, match="malformed character manifest"):
        load_character(package)


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ('llm = "ollama"', "llm must be a TOML table"),
        ("[llm]\nprovider = \"ollama\"", "requires.*model"),
        ("[llm]\nprovider = 4\nmodel = \"model\"", "requires.*provider"),
        ("[llm]\nprovider = \"Open AI\"\nmodel = \"model\"", "invalid LLM"),
        ('tts = "piper"', "tts must be a TOML table"),
        ("[tts]\nprovider = \"piper\"", "requires.*voice"),
        ("[tts]\nprovider = 4\nvoice = \"voice\"", "requires.*provider"),
        ("[tts]\nprovider = \"Eleven Labs\"\nvoice = \"voice\"", "invalid TTS"),
    ],
)
def test_provider_section_validation(
    tmp_path: Path, section: str, message: str
) -> None:
    manifest = minimal_manifest() + "\n" + section
    with pytest.raises(CharacterError, match=message):
        load_character(write_manifest(tmp_path / "character", manifest))


@pytest.mark.parametrize(
    "provider_section",
    [
        '[llm]\nprovider = "openai"\nmodel = "gpt-example"',
        '[llm]\nprovider = "openrouter"\nmodel = "provider/model"',
        '[tts]\nprovider = "elevenlabs"\nvoice = "voice-id"',
    ],
)
def test_future_provider_identifiers_are_data_only(
    tmp_path: Path, provider_section: str
) -> None:
    character = load_character(
        write_manifest(
            tmp_path / "character", minimal_manifest() + "\n" + provider_section
        )
    )

    assert character.llm is not None or character.tts is not None


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ("settings = 4", "settings must be a TOML table"),
        ("[llm.settings]\nstops = [\"one\"]", "must be a string.*boolean"),
        ("[llm.settings]\ntemperature = inf", "must be finite"),
        ("[llm.settings]\napi_key = \"secret\"", "secrets are not allowed"),
    ],
)
def test_provider_settings_reject_unsupported_values_and_secrets(
    tmp_path: Path, settings: str, message: str
) -> None:
    manifest = (
        minimal_manifest()
        + '\n[llm]\nprovider = "ollama"\nmodel = "model"\n'
        + settings
    )
    with pytest.raises(CharacterError, match=message):
        load_character(write_manifest(tmp_path / "character", manifest))


@pytest.mark.parametrize(
    "secret_key",
    ["openai_api_key", "client_secret", "bearer_token", "token", "MY_PASSWORD"],
)
def test_compound_and_case_insensitive_secret_setting_names_are_rejected(
    tmp_path: Path, secret_key: str
) -> None:
    manifest = (
        minimal_manifest()
        + '\n[llm]\nprovider = "ollama"\nmodel = "model"'
        + f'\n[llm.settings]\n{secret_key} = "must not be stored"'
    )

    with pytest.raises(CharacterError, match="secrets are not allowed"):
        load_character(write_manifest(tmp_path / "character", manifest))


def test_non_secret_provider_settings_remain_valid(tmp_path: Path) -> None:
    manifest = (
        minimal_manifest()
        + '\n[llm]\nprovider = "ollama"\nmodel = "model"'
        + '\n[llm.settings]\ntemperature = 0.8\nspeed = 1.0'
        + '\ntimeout = 30\ntop_p = 0.9'
    )

    character = load_character(write_manifest(tmp_path / "character", manifest))

    assert character.llm is not None
    assert character.llm.settings == {
        "temperature": 0.8,
        "speed": 1.0,
        "timeout": 30,
        "top_p": 0.9,
    }


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('visuals = "image.png"', "visuals must be a TOML table"),
        ('sounds = ["sound.wav"]', "sounds must be a TOML table"),
        ('[visuals]\nidle = { path = "idle.png" }', "must be a non-empty relative"),
        ('[sounds]\n"Bad Name" = "sound.wav"', "invalid asset name"),
    ],
)
def test_asset_table_validation(tmp_path: Path, table: str, message: str) -> None:
    with pytest.raises(CharacterError, match=message):
        load_character(
            write_manifest(tmp_path / "character", minimal_manifest() + "\n" + table)
        )


@pytest.mark.parametrize(
    "asset_path",
    ["/etc/passwd", "C:\\Windows\\secret", "../outside.png", "visuals/../idle.png"],
)
def test_absolute_and_parent_asset_paths_are_rejected(
    tmp_path: Path, asset_path: str
) -> None:
    manifest = minimal_manifest() + f"\n[visuals]\nidle = {asset_path!r}"
    with pytest.raises(CharacterError, match="absolute path|parent traversal"):
        load_character(write_manifest(tmp_path / "character", manifest))


def test_existing_symlink_cannot_escape_package(tmp_path: Path) -> None:
    package = write_manifest(
        tmp_path / "character",
        minimal_manifest() + '\n[visuals]\nidle = "visuals/escape.png"',
    )
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not loaded")
    (package / "visuals").mkdir()
    (package / "visuals" / "escape.png").symlink_to(outside)

    with pytest.raises(CharacterError, match="escapes the character package"):
        load_character(package)


def test_relative_paths_are_portable_when_package_moves(tmp_path: Path) -> None:
    original = write_manifest(
        tmp_path / "original",
        minimal_manifest()
        + '\n[visuals]\nidle = "visuals/idle.png"'
        + '\n[sounds]\nstartup = "sounds/startup.wav"',
    )
    first = load_character(original)
    moved = tmp_path / "moved" / "character"
    moved.parent.mkdir()
    shutil.move(original, moved)
    second = load_character(moved)

    assert first.visuals["idle"] == (original / "visuals/idle.png").resolve()
    assert second.visuals["idle"] == (moved / "visuals/idle.png").resolve()
    assert second.sounds["startup"] == (moved / "sounds/startup.wav").resolve()


def test_asset_environment_variable_is_literal_package_relative_text(
    tmp_path: Path,
) -> None:
    package = write_manifest(
        tmp_path / "character",
        minimal_manifest() + '\n[visuals]\nidle = "$HOME/not-expanded.png"',
    )

    character = load_character(package)

    assert character.visuals["idle"] == (
        package / "$HOME" / "not-expanded.png"
    ).resolve()


def test_manifest_data_is_not_executed_or_imported(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    manifest = minimal_manifest() + f'\ncommand = "touch {marker}"'

    with pytest.raises(CharacterError, match="unsupported field"):
        load_character(write_manifest(tmp_path / "character", manifest))
    assert not marker.exists()
