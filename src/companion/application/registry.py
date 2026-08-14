from collections.abc import Callable
from typing import Generic, TypeVar

from companion.application.errors import CompositionError
from companion.character.definition import LLMPreference, TTSPreference
from companion.llm.interfaces import LLMProvider
from companion.tts.interfaces import TTSProvider


PreferenceT = TypeVar("PreferenceT")
ContextT = TypeVar("ContextT")
ProviderT = TypeVar("ProviderT")
ProviderFactory = Callable[[PreferenceT, ContextT], ProviderT]


class ProviderRegistry(Generic[PreferenceT, ContextT, ProviderT]):
    """Explicit, resource-free mapping from identifiers to provider factories."""

    def __init__(self, provider_kind: str) -> None:
        self._provider_kind = provider_kind
        self._factories: dict[str, ProviderFactory[PreferenceT, ContextT, ProviderT]] = {}

    def register(
        self,
        identifier: str,
        factory: ProviderFactory[PreferenceT, ContextT, ProviderT],
    ) -> None:
        if not identifier:
            raise CompositionError(f"{self._provider_kind} provider identifier is empty")
        if identifier in self._factories:
            raise CompositionError(
                f"{self._provider_kind} provider {identifier!r} is already registered"
            )
        self._factories[identifier] = factory

    def _create(
        self, identifier: str, preference: PreferenceT, context: ContextT
    ) -> ProviderT:
        try:
            factory = self._factories[identifier]
        except KeyError as exc:
            raise CompositionError(
                f"unsupported {self._provider_kind} provider {identifier!r}"
            ) from exc
        return factory(preference, context)


class LLMProviderRegistry(ProviderRegistry[LLMPreference, ContextT, LLMProvider]):
    def __init__(self) -> None:
        super().__init__("LLM")

    def create(
        self, preference: LLMPreference, context: ContextT
    ) -> LLMProvider:
        return self._create(preference.provider, preference, context)


class TTSProviderRegistry(ProviderRegistry[TTSPreference, ContextT, TTSProvider]):
    def __init__(self) -> None:
        super().__init__("TTS")

    def create(
        self, preference: TTSPreference, context: ContextT
    ) -> TTSProvider:
        return self._create(preference.provider, preference, context)
