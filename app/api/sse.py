import asyncio
import json
from typing import Any, Dict, Optional

from app.projects import ProjectStore
from starlette.concurrency import run_in_threadpool


class EventBridge:
    """Publish/subscribe event bus with SQLite-backed persistence and replay."""

    def __init__(self, db_path: Optional[str] = None):
        self.store = ProjectStore(db_path)
        self._queues: Dict[str, Dict[int, asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(scope: str, scope_id: str) -> str:
        return f"{scope}:{scope_id}"

    async def next_event_id(self, scope: str, scope_id: str) -> int:
        events = await run_in_threadpool(
            self.store.list_sse_events, scope, scope_id, limit=10_000_000
        )
        if not events:
            return 1
        return max(event["event_id"] for event in events) + 1

    async def publish(self, scope: str, scope_id: str, data: Any) -> int:
        event_id = await self.next_event_id(scope, scope_id)
        payload = json.dumps(data, ensure_ascii=False)
        await run_in_threadpool(
            self.store.record_sse_event, scope, scope_id, event_id, payload
        )

        key = self._key(scope, scope_id)
        async with self._lock:
            subscribers = list(self._queues.get(key, {}).values())

        for queue in subscribers:
            await queue.put({"event_id": event_id, "data": data})

        return event_id

    async def subscribe(
        self, scope: str, scope_id: str, last_event_id: int = 0
    ) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        key = self._key(scope, scope_id)

        max_event_id = await self.next_event_id(scope, scope_id) - 1

        async with self._lock:
            self._queues.setdefault(key, {})[id(queue)] = queue

        historical = await run_in_threadpool(
            self.store.list_sse_events,
            scope,
            scope_id,
            after_event_id=last_event_id,
            limit=10_000_000,
        )
        for event in historical:
            if event["event_id"] > max_event_id:
                continue
            await queue.put(
                {"event_id": event["event_id"], "data": json.loads(event["data"])}
            )

        return queue

    async def unsubscribe(self, scope: str, scope_id: str, queue: asyncio.Queue) -> None:
        key = self._key(scope, scope_id)
        async with self._lock:
            subscribers = self._queues.get(key)
            if subscribers is None:
                return
            subscribers.pop(id(queue), None)
            if not subscribers:
                del self._queues[key]
