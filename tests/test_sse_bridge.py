import pytest

from app.api.sse import EventBridge


@pytest.fixture
def bridge(tmp_path):
    db_path = tmp_path / "sse.db"
    return EventBridge(str(db_path))


def test_next_event_id_starts_at_one(bridge):
    assert bridge.next_event_id("run", "run-1") == 1


def test_next_event_id_increments(bridge):
    bridge.store.record_sse_event("run", "run-1", 1, "{}")
    bridge.store.record_sse_event("run", "run-1", 2, "{}")
    assert bridge.next_event_id("run", "run-1") == 3


@pytest.mark.anyio
async def test_subscribe_receives_published_event(bridge):
    queue = await bridge.subscribe("run", "run-1")

    event_id = await bridge.publish("run", "run-1", {"message": "hello"})

    received = await queue.get()
    assert received["event_id"] == event_id
    assert received["data"] == {"message": "hello"}
