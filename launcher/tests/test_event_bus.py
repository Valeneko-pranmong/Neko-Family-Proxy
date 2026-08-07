from neko_launcher.domain.events import AuthStarted
from neko_launcher.infrastructure.storage.event_bus import EventBus


def test_event_bus_preserves_order_and_drains() -> None:
    bus = EventBus()
    bus.publish(AuthStarted("one@example.com"))
    bus.publish(AuthStarted("two@example.com"))

    events = bus.drain()

    assert [event.email for event in events] == [
        "one@example.com",
        "two@example.com",
    ]
    assert bus.drain() == []
