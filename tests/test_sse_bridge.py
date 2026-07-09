import asyncio

import pytest

from app.api.sse import EventBridge


@pytest.fixture
def bridge(tmp_path):
    db_path = tmp_path / "sse.db"
    return EventBridge(str(db_path))


@pytest.mark.anyio
async def test_next_event_id_starts_at_one(bridge):
    assert await bridge.next_event_id("run", "run-1") == 1


@pytest.mark.anyio
async def test_next_event_id_increments(bridge):
    bridge.store.record_sse_event("run", "run-1", 1, "{}")
    bridge.store.record_sse_event("run", "run-1", 2, "{}")
    assert await bridge.next_event_id("run", "run-1") == 3


@pytest.mark.anyio
async def test_subscribe_receives_published_event(bridge):
    queue = await bridge.subscribe("run", "run-1")

    event_id = await bridge.publish("run", "run-1", {"message": "hello"})

    received = await queue.get()
    assert received["event_id"] == event_id
    assert received["data"] == {"message": "hello"}


@pytest.mark.anyio
async def test_subscribe_replays_historical_events(bridge):
    event_ids = []
    for i in range(3):
        event_id = await bridge.publish("run", "run-1", {"index": i})
        event_ids.append(event_id)

    queue = await bridge.subscribe("run", "run-1", last_event_id=0)

    received = []
    for _ in range(3):
        received.append(await asyncio.wait_for(queue.get(), timeout=1.0))

    assert [r["event_id"] for r in received] == event_ids
    assert [r["data"] for r in received] == [{"index": i} for i in range(3)]


@pytest.mark.anyio
async def test_unsubscribe_removes_queue(bridge):
    queue = await bridge.subscribe("run", "run-1")

    await bridge.unsubscribe("run", "run-1", queue)

    await bridge.publish("run", "run-1", {"message": "hello"})

    # Yield control so any pending delivery would land in the queue.
    await asyncio.sleep(0)

    assert queue.empty()


@pytest.mark.anyio
async def test_concurrent_publish_no_duplicate_ids(bridge):
    async def publisher(publisher_id: int):
        for i in range(10):
            await bridge.publish("run", "run-1", {"publisher": publisher_id, "index": i})

    await asyncio.gather(*[publisher(p) for p in range(5)])

    events = bridge.store.list_sse_events("run", "run-1", limit=10_000_000)
    event_ids = [e["event_id"] for e in events]
    assert len(event_ids) == 50
    assert len(set(event_ids)) == 50
    assert sorted(event_ids) == list(range(1, 51))


@pytest.mark.anyio
async def test_subscribe_does_not_lose_events_during_replay(bridge):
    # Pre-publish a few events so the subscriber definitely has historical replay work.
    for i in range(5):
        await bridge.publish("run", "run-1", {"index": i})

    async def publisher():
        for i in range(5, 20):
            await bridge.publish("run", "run-1", {"index": i})
            # Yield control so subscribe can interleave with publishing.
            await asyncio.sleep(0)

    async def subscriber():
        queue = await bridge.subscribe("run", "run-1", last_event_id=0)
        received = []
        for _ in range(20):
            event = await asyncio.wait_for(queue.get(), timeout=2.0)
            received.append(event["event_id"])
        return received

    _, received = await asyncio.gather(publisher(), subscriber())
    assert received == list(range(1, 21))
