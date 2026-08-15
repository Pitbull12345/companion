from pathlib import Path

from companion.character import AnimationDefinition
from companion.frontend.animation import AnimationController, AnimationScheduler


def animation(*names: str, loop: bool = True) -> AnimationDefinition:
    return AnimationDefinition(tuple(Path(name) for name in names), 5.0, loop)


def test_controller_starts_at_first_frame_and_loops_deterministically() -> None:
    controller = AnimationController()
    frames = animation("0.png", "1.png", "2.png")

    assert controller.activate(frames) == Path("0.png")
    assert controller.advance() == Path("1.png")
    assert controller.advance() == Path("2.png")
    assert controller.advance() == Path("0.png")


def test_non_looping_controller_stays_on_final_frame() -> None:
    controller = AnimationController()
    controller.activate(animation("0.png", "1.png", loop=False))

    assert controller.advance() == Path("1.png")
    assert not controller.can_advance
    assert controller.advance() == Path("1.png")


def test_animation_change_resets_index_and_invalidates_stale_generation() -> None:
    controller = AnimationController()
    controller.activate(animation("old-0.png", "old-1.png"))
    old_generation = controller.generation
    controller.advance()

    assert controller.activate(animation("new-0.png", "new-1.png")) == Path(
        "new-0.png"
    )
    assert controller.frame_index == 0
    assert controller.generation != old_generation


class FakeTimers:
    def __init__(self) -> None:
        self.callbacks: dict[int, object] = {}
        self.intervals: list[int] = []
        self.removed: list[int] = []
        self.next_id = 1

    def schedule(self, interval: int, callback) -> int:
        source = self.next_id
        self.next_id += 1
        self.intervals.append(interval)
        self.callbacks[source] = callback
        return source

    def remove(self, source: object) -> None:
        assert isinstance(source, int)
        self.removed.append(source)
        self.callbacks.pop(source, None)


def test_scheduler_owns_one_timer_advances_and_removes_old_timer() -> None:
    timers = FakeTimers()
    shown: list[Path] = []
    scheduler = AnimationScheduler(timers.schedule, timers.remove, shown.append)
    first = animation("a0.png", "a1.png")
    second = animation("b0.png", "b1.png")

    scheduler.activate(first)
    assert timers.intervals == [200]
    assert shown == [Path("a0.png")]
    first_callback = timers.callbacks[1]
    assert callable(first_callback)
    assert first_callback() is True
    assert shown[-1] == Path("a1.png")

    scheduler.activate(second)
    assert timers.removed == [1]
    assert len(timers.callbacks) == 1
    assert shown[-1] == Path("b0.png")
    assert first_callback() is False
    assert shown[-1] == Path("b0.png")


def test_scheduler_avoids_same_animation_churn_and_static_has_no_timer() -> None:
    timers = FakeTimers()
    shown: list[Path] = []
    scheduler = AnimationScheduler(timers.schedule, timers.remove, shown.append)
    sequence = animation("0.png", "1.png")

    scheduler.activate(sequence)
    scheduler.activate(sequence)
    assert timers.intervals == [200]
    assert timers.removed == []

    scheduler.activate(Path("static.png"))
    assert timers.removed == [1]
    assert shown[-1] == Path("static.png")
    assert not scheduler.timer_active


def test_non_looping_timer_stops_and_shutdown_removes_active_timer() -> None:
    timers = FakeTimers()
    shown: list[Path] = []
    scheduler = AnimationScheduler(timers.schedule, timers.remove, shown.append)

    scheduler.activate(animation("0.png", "1.png", loop=False))
    callback = timers.callbacks[1]
    assert callable(callback)
    assert callback() is False
    assert shown[-1] == Path("1.png")
    assert not scheduler.timer_active

    scheduler.activate(animation("a.png", "b.png"))
    scheduler.stop()
    assert timers.removed == [2]
    assert not scheduler.timer_active
