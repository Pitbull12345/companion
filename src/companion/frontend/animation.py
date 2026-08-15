from collections.abc import Callable
from pathlib import Path

from companion.character import AnimationDefinition


VisualAsset = Path | AnimationDefinition


class AnimationController:
    """Deterministic frame state with no clock or GUI dependencies."""

    def __init__(self) -> None:
        self.animation: AnimationDefinition | None = None
        self.frame_index = 0
        self.generation = 0

    @property
    def current_frame(self) -> Path | None:
        if self.animation is None:
            return None
        return self.animation.frames[self.frame_index]

    @property
    def can_advance(self) -> bool:
        if self.animation is None or len(self.animation.frames) < 2:
            return False
        return self.animation.loop or self.frame_index < len(self.animation.frames) - 1

    def activate(self, animation: AnimationDefinition | None) -> Path | None:
        self.animation = animation
        self.frame_index = 0
        self.generation += 1
        return self.current_frame

    def advance(self) -> Path | None:
        if self.animation is None:
            return None
        final_index = len(self.animation.frames) - 1
        if self.frame_index < final_index:
            self.frame_index += 1
        elif self.animation.loop:
            self.frame_index = 0
        return self.current_frame


class AnimationScheduler:
    """Own at most one presentation-context timer for one pet."""

    def __init__(
        self,
        schedule: Callable[[int, Callable[[], bool]], object],
        remove: Callable[[object], None],
        show_frame: Callable[[Path], None],
    ) -> None:
        self._schedule = schedule
        self._remove = remove
        self._show_frame = show_frame
        self._controller = AnimationController()
        self._source: object | None = None
        self._asset: VisualAsset | None = None
        self._animate = False

    @property
    def timer_active(self) -> bool:
        return self._source is not None

    def activate(self, asset: VisualAsset | None, *, animate: bool = True) -> None:
        if asset == self._asset and animate == self._animate:
            return
        self.stop()
        self._asset = asset
        self._animate = animate
        if asset is None:
            return
        if isinstance(asset, Path):
            self._controller.activate(None)
            self._show_frame(asset)
            return

        frame = self._controller.activate(asset)
        if frame is not None:
            self._show_frame(frame)
        if not animate or not self._controller.can_advance:
            return

        generation = self._controller.generation

        def tick() -> bool:
            if generation != self._controller.generation:
                return False
            frame = self._controller.advance()
            if frame is not None:
                self._show_frame(frame)
            keep = self._controller.can_advance
            if not keep:
                self._source = None
            return keep

        interval_ms = max(1, round(1000 / asset.fps))
        self._source = self._schedule(interval_ms, tick)

    def stop(self) -> None:
        if self._source is not None:
            self._remove(self._source)
            self._source = None
        self._controller.activate(None)
        self._asset = None
        self._animate = False
