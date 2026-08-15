from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias
from collections.abc import Mapping


ProviderSetting: TypeAlias = str | int | float | bool


def _empty_settings() -> Mapping[str, ProviderSetting]:
    return MappingProxyType({})


def _empty_assets() -> Mapping[str, Path]:
    return MappingProxyType({})


def _empty_animations() -> Mapping[str, "AnimationDefinition"]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class AnimationDefinition:
    frames: tuple[Path, ...]
    fps: float
    loop: bool = True


@dataclass(frozen=True, slots=True)
class LLMPreference:
    provider: str
    model: str
    settings: Mapping[str, ProviderSetting] = field(default_factory=_empty_settings)


@dataclass(frozen=True, slots=True)
class TTSPreference:
    provider: str
    voice: str
    settings: Mapping[str, ProviderSetting] = field(default_factory=_empty_settings)


@dataclass(frozen=True, slots=True)
class CharacterDefinition:
    id: str
    name: str
    system_prompt: str
    package_root: Path
    description: str | None = None
    llm: LLMPreference | None = None
    tts: TTSPreference | None = None
    visuals: Mapping[str, Path] = field(default_factory=_empty_assets)
    sounds: Mapping[str, Path] = field(default_factory=_empty_assets)
    animations: Mapping[str, AnimationDefinition] = field(
        default_factory=_empty_animations
    )
