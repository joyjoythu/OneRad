import asyncio
import json
import threading
import time
from contextlib import suppress

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


@pytest.mark.anyio
async def test_subscribe_receives_events_in_order_during_replay(bridge):
    # Pre-publish events 1-10 so the subscriber has historical replay work.
    for i in range(1, 11):
        await bridge.publish("run", "run-1", {"index": i})

    # Slow down the historical replay so live publishes race against it.
    original_list = bridge.store.list_sse_events

    def slow_list_sse_events(*args, **kwargs):
        time.sleep(0.1)
        return original_list(*args, **kwargs)

    bridge.store.list_sse_events = slow_list_sse_events

    received = []

    async def subscriber():
        queue = await bridge.subscribe("run", "run-1", last_event_id=0)
        for _ in range(20):
            event = await asyncio.wait_for(queue.get(), timeout=2.0)
            received.append(event["event_id"])
        return received

    async def publisher():
        # Yield control so the subscriber begins replay first.
        await asyncio.sleep(0)
        for i in range(11, 21):
            await bridge.publish("run", "run-1", {"index": i})
            await asyncio.sleep(0)

    results = await asyncio.gather(subscriber(), publisher())
    assert results[0] == list(range(1, 21))


@pytest.mark.anyio
async def test_publish_cancelled_mid_write_keeps_ids_unique_and_events(bridge):
    """回归：发布者被取消时，其写入仍落库且事件 id 不复用。

    旧实现从 store max 分配 id：被取消的写入尚未落库时，下一次发布会分到
    相同 id，INSERT OR IGNORE 静默丢弃其中一个事件。
    """
    write1_started = threading.Event()
    release_write1 = threading.Event()
    write1_finished = threading.Event()
    original_record = bridge.store.record_sse_event
    first_call = {"done": False}

    def blocking_record(scope, scope_id, event_id, data):
        # Runs in a worker thread, hence threading.Event rather than asyncio.
        if not first_call["done"]:
            first_call["done"] = True
            write1_started.set()
            assert release_write1.wait(timeout=5)
            try:
                return original_record(scope, scope_id, event_id, data)
            finally:
                write1_finished.set()
        return original_record(scope, scope_id, event_id, data)

    bridge.store.record_sse_event = blocking_record

    task_a = asyncio.create_task(bridge.publish("s", "id1", {"n": 1}))
    assert await asyncio.to_thread(write1_started.wait, 2)

    task_a.cancel()
    with suppress(asyncio.CancelledError):
        await task_a

    # The abandoned write has not landed yet; this publish must still get a
    # fresh id and its own write must complete.
    id_b = await bridge.publish("s", "id1", {"n": 2})

    release_write1.set()
    assert await asyncio.to_thread(write1_finished.wait, 2)

    events = bridge.store.list_sse_events("s", "id1", limit=10)
    assert id_b == 2
    assert [e["event_id"] for e in events] == [1, 2]
    assert [json.loads(e["data"])["n"] for e in events] == [1, 2]
    # In the fixed bridge this also awaits the abandoned pending write.
    assert await bridge.next_event_id("s", "id1") == 3
