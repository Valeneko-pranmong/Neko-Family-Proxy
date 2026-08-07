from __future__ import annotations

from collections import deque
from threading import Lock
from typing import TypeVar

from neko_launcher.domain.events import Event

T = TypeVar("T", bound=Event)


class EventBus:
    """Small thread-safe event queue; UI drains it from the main thread."""

    def __init__(self) -> None:
        self._events: deque[Event] = deque()
        self._lock = Lock()

    def publish(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)

    def drain(self, limit: int = 100) -> list[Event]:
        events: list[Event] = []
        with self._lock:
            while self._events and len(events) < limit:
                events.append(self._events.popleft())
        return events
