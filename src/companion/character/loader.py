import math
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePath, PureWindowsPath
from types import MappingProxyType
from typing import Any

from companion.character.definition import (
    AnimationDefinition,
    CharacterDefinition,
    LLMPreference,
    ProviderSetting,
    TTSPreference,
)
from companion.character.errors import CharacterError


_CHARACTER_ID = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")
_PROVIDER_ID = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")
_ASSET_NAME = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")
_TOP_LEVEL_FIELDS = {
    "id",
    "name",
    "description",
    "system_prompt",
    "llm",
    "tts",
    "visuals",
    "sounds",
    "animations",
}
_ANIMATION_KEYS = {
    "idle",
    "listening",
    "transcribing",
    "thinking",
    "speaking",
    "error",
}
_MAX_ANIMATION_FPS = 60.0
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SECRET_COMPONENTS = {
    "apikey",
    "password",
    "secret",
    "credential",
    "credentials",
    "token",
}


def _required_text(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CharacterError(f"character manifest requires non-empty {field!r}")
    return value


def _optional_text(data: Mapping[str, Any], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CharacterError(f"character manifest field {field!r} must be non-empty text")
    return value


def _validate_table_fields(
    table: Mapping[str, Any], allowed: set[str], section: str
) -> None:
    unknown = set(table) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise CharacterError(f"unsupported field in {section}: {names}")


def _is_secret_setting(key: str) -> bool:
    components = tuple(
        component for component in re.split(r"[^a-z0-9]+", key.casefold()) if component
    )
    if any(component in _SECRET_COMPONENTS for component in components):
        return True
    return any(
        first == "api" and second == "key"
        for first, second in zip(components, components[1:])
    )


def _settings(value: Any, section: str) -> Mapping[str, ProviderSetting]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise CharacterError(f"{section}.settings must be a TOML table")

    validated: dict[str, ProviderSetting] = {}
    for key, setting in value.items():
        if not isinstance(key, str) or not key:
            raise CharacterError(f"{section}.settings contains an invalid key")
        if _is_secret_setting(key):
            raise CharacterError(f"secrets are not allowed in character settings: {key}")
        if not isinstance(setting, (str, int, float, bool)):
            raise CharacterError(
                f"{section}.settings.{key} must be a string, integer, float, or boolean"
            )
        if isinstance(setting, float) and not math.isfinite(setting):
            raise CharacterError(f"{section}.settings.{key} must be finite")
        validated[key] = setting
    return MappingProxyType(validated)


def _llm_preference(value: Any) -> LLMPreference | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CharacterError("llm must be a TOML table")
    _validate_table_fields(value, {"provider", "model", "settings"}, "llm")
    provider = _required_text(value, "provider")
    if _PROVIDER_ID.fullmatch(provider) is None:
        raise CharacterError(f"invalid LLM provider identifier: {provider!r}")
    return LLMPreference(
        provider=provider,
        model=_required_text(value, "model"),
        settings=_settings(value.get("settings"), "llm"),
    )


def _tts_preference(value: Any) -> TTSPreference | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CharacterError("tts must be a TOML table")
    _validate_table_fields(value, {"provider", "voice", "settings"}, "tts")
    provider = _required_text(value, "provider")
    if _PROVIDER_ID.fullmatch(provider) is None:
        raise CharacterError(f"invalid TTS provider identifier: {provider!r}")
    return TTSPreference(
        provider=provider,
        voice=_required_text(value, "voice"),
        settings=_settings(value.get("settings"), "tts"),
    )


def _asset_path(package_root: Path, value: Any, section: str, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CharacterError(f"{section}.{name} must be a non-empty relative path")
    reference = PurePath(value)
    if reference.is_absolute() or PureWindowsPath(value).is_absolute():
        raise CharacterError(f"{section}.{name} must not be an absolute path")
    if ".." in reference.parts:
        raise CharacterError(f"{section}.{name} must not contain parent traversal")

    resolved = (package_root / reference).resolve()
    if not resolved.is_relative_to(package_root):
        raise CharacterError(f"{section}.{name} escapes the character package")
    return resolved


def _assets(value: Any, package_root: Path, section: str) -> Mapping[str, Path]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise CharacterError(f"{section} must be a TOML table")

    resolved: dict[str, Path] = {}
    for name, path_value in value.items():
        if not isinstance(name, str) or _ASSET_NAME.fullmatch(name) is None:
            raise CharacterError(f"{section} contains invalid asset name {name!r}")
        resolved[name] = _asset_path(package_root, path_value, section, name)
    return MappingProxyType(resolved)


def _animation_frame(package_root: Path, value: Any, name: str, index: int) -> Path:
    label = f"animations.{name}.frames[{index}]"
    path = _asset_path(package_root, value, f"animations.{name}.frames", str(index))
    if path.suffix.casefold() != ".png":
        raise CharacterError(f"{label} must reference a PNG file")
    if not path.is_file():
        raise CharacterError(f"{label} was not found or is not a regular file: {path}")
    try:
        with path.open("rb") as frame:
            signature = frame.read(8)
    except OSError as exc:
        raise CharacterError(f"{label} could not be read: {path}") from exc
    if signature != _PNG_SIGNATURE:
        raise CharacterError(f"{label} is not a valid PNG file: {path}")
    return path


def _animations(
    value: Any, package_root: Path
) -> Mapping[str, AnimationDefinition]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise CharacterError("animations must be a TOML table")

    definitions: dict[str, AnimationDefinition] = {}
    for name, animation in value.items():
        if name not in _ANIMATION_KEYS:
            raise CharacterError(f"animations contains unsupported state {name!r}")
        if not isinstance(animation, dict):
            raise CharacterError(f"animations.{name} must be a TOML table")
        _validate_table_fields(animation, {"frames", "fps", "loop"}, f"animations.{name}")
        frames = animation.get("frames")
        if not isinstance(frames, list) or not frames:
            raise CharacterError(f"animations.{name}.frames must be a non-empty array")
        fps = animation.get("fps")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)):
            raise CharacterError(f"animations.{name}.fps must be a number")
        numeric_fps = float(fps)
        if not math.isfinite(numeric_fps) or not 0 < numeric_fps <= _MAX_ANIMATION_FPS:
            raise CharacterError(
                f"animations.{name}.fps must be finite and greater than 0 "
                f"and at most {_MAX_ANIMATION_FPS:g}"
            )
        loop = animation.get("loop", True)
        if not isinstance(loop, bool):
            raise CharacterError(f"animations.{name}.loop must be a boolean")
        definitions[name] = AnimationDefinition(
            frames=tuple(
                _animation_frame(package_root, frame, name, index)
                for index, frame in enumerate(frames)
            ),
            fps=numeric_fps,
            loop=loop,
        )
    return MappingProxyType(definitions)


class CharacterLoader:
    """Load portable metadata and strictly validate declared animation frames."""

    def load(self, package_directory: str | Path) -> CharacterDefinition:
        package_root = Path(package_directory).expanduser().resolve()
        manifest_path = package_root / "character.toml"
        try:
            with manifest_path.open("rb") as manifest:
                data = tomllib.load(manifest)
        except FileNotFoundError as exc:
            raise CharacterError(f"character manifest not found: {manifest_path}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise CharacterError(f"malformed character manifest: {exc}") from exc
        except OSError as exc:
            raise CharacterError(f"could not read character manifest: {exc}") from exc

        if not isinstance(data, dict):
            raise CharacterError("character manifest must be a TOML table")
        _validate_table_fields(data, _TOP_LEVEL_FIELDS, "character manifest")

        character_id = _required_text(data, "id")
        if _CHARACTER_ID.fullmatch(character_id) is None:
            raise CharacterError(f"invalid character id: {character_id!r}")

        return CharacterDefinition(
            id=character_id,
            name=_required_text(data, "name"),
            system_prompt=_required_text(data, "system_prompt"),
            package_root=package_root,
            description=_optional_text(data, "description"),
            llm=_llm_preference(data.get("llm")),
            tts=_tts_preference(data.get("tts")),
            visuals=_assets(data.get("visuals"), package_root, "visuals"),
            sounds=_assets(data.get("sounds"), package_root, "sounds"),
            animations=_animations(data.get("animations"), package_root),
        )


def load_character(package_directory: str | Path) -> CharacterDefinition:
    return CharacterLoader().load(package_directory)
