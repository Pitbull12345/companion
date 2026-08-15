from collections.abc import Callable

from companion.events import ApplicationEvent


class ScheduledEventObserver:
    """Transfer ordered runtime events to an owning presentation context."""

    def __init__(
        self,
        schedule: Callable[[Callable[[], bool]], object],
        consume: Callable[[ApplicationEvent], None],
    ) -> None:
        self._schedule = schedule
        self._consume = consume

    def publish(self, event: ApplicationEvent) -> None:
        def deliver() -> bool:
            self._consume(event)
            return False

        self._schedule(deliver)
