import asyncio
import json
from contextlib import suppress
from typing import Any, Dict, Optional, Set

from app.projects import ProjectStore
from starlette.concurrency import run_in_threadpool


class EventBridge:
    """Publish/subscribe event bus with SQLite-backed persistence and replay."""

    def __init__(self, db_path: Optional[str] = None):
        self.store = ProjectStore(db_path)
        self._queues: Dict[str, Dict[int, asyncio.Queue]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        # Per-scope in-memory monotonic id allocator. Ids stay unique per scope
        # even if a write is abandoned mid-publish, so INSERT OR IGNORE can
        # never silently drop an event. Trade-off: a failed write permanently
        # burns its allocated id, leaving a gap — gaps are safe (replay only
        # compares event_id > last_event_id), so do not "optimize" this back
        # to store-max allocation.
        self._next_ids: Dict[str, int] = {}
        # Per-scope set of in-flight store writes. Each write runs in its own
        # task shielded from publisher cancellation (see publish), so it only
        # completes once the store write has actually landed.
        self._pending_writes: Dict[str, Set[asyncio.Task]] = {}

    @staticmethod
    def _key(scope: str, scope_id: str) -> str:
        return f"{scope}:{scope_id}"

    def _scope_lock(self, scope: str, scope_id: str) -> asyncio.Lock:
        key = self._key(scope, scope_id)
        return self._locks.setdefault(key, asyncio.Lock())

    async def _allocate_event_id(self, key: str, scope: str, scope_id: str) -> int:
        """Return the next id for the scope. Caller must hold the scope lock."""
        next_id = self._next_ids.get(key)
        if next_id is None:
            next_id = await run_in_threadpool(
                self.store.get_max_event_id, scope, scope_id
            ) + 1
        self._next_ids[key] = next_id + 1
        return next_id

    def _track_write(self, key: str, write_task: asyncio.Task) -> None:
        pending = self._pending_writes.setdefault(key, set())
        pending.add(write_task)

        def _on_done(task: asyncio.Task) -> None:
            pending.discard(task)
            if not pending:
                self._pending_writes.pop(key, None)
            # Retrieve the exception so a failed write does not trigger
            # "exception was never retrieved" noise. Swallowing it is safe:
            # a failed write burns its allocated id, leaving a gap, and
            # replay only compares event_id > last_event_id.
            with suppress(BaseException):
                task.exception()

        write_task.add_done_callback(_on_done)

    async def _await_pending_writes(self, key: str) -> None:
        for task in list(self._pending_writes.get(key, ())):
            # A failed/cancelled earlier write must not break readers.
            with suppress(BaseException):
                await task

    async def next_event_id(self, scope: str, scope_id: str) -> int:
        key = self._key(scope, scope_id)
        await self._await_pending_writes(key)
        max_id = await run_in_threadpool(
            self.store.get_max_event_id, scope, scope_id
        )
        return max_id + 1

    async def publish(
        self, scope: str, scope_id: str, data: Any, *, persist: bool = True
    ) -> int:
        payload = json.dumps(data, ensure_ascii=False)
        lock = self._scope_lock(scope, scope_id)
        key = self._key(scope, scope_id)

        async with lock:
            event_id = await self._allocate_event_id(key, scope, scope_id)
            if persist:
                write_task = asyncio.ensure_future(
                    run_in_threadpool(
                        self.store.record_sse_event, scope, scope_id, event_id, payload
                    )
                )
                self._track_write(key, write_task)
                # shield 阻止发布者被取消时取消传播进写任务：写任务只在 store
                # 写入真正落库后才完成。若发布者在等待期间被取消，写入仍会落库
                # （回放/重连可获取；流结束时前端还会同步最终状态），仅本次
                # 不再向订阅队列投递。
                await asyncio.shield(write_task)
            for queue in self._queues.get(key, {}).values():
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await queue.put({"event_id": event_id, "data": data})

        return event_id

    async def subscribe(
        self, scope: str, scope_id: str, last_event_id: int = 0
    ) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        key = self._key(scope, scope_id)
        lock = self._scope_lock(scope, scope_id)

        async with lock:
            # Observe the store only after in-flight writes for this scope land.
            await self._await_pending_writes(key)
            max_event_id = await self.next_event_id(scope, scope_id) - 1
            self._queues.setdefault(key, {})[id(queue)] = queue

            historical = await run_in_threadpool(
                self.store.list_sse_events,
                scope,
                scope_id,
                after_event_id=last_event_id,
                limit=10_000_000,
            )
            for event in historical:
                # Safety net: historical fetch happened under the lock, so this
                # should always be true. Kept to guard against stale reads.
                if event["event_id"] > max_event_id:
                    continue
                await queue.put(
                    {"event_id": event["event_id"], "data": json.loads(event["data"])}
                )

        return queue

    async def unsubscribe(self, scope: str, scope_id: str, queue: asyncio.Queue) -> None:
        key = self._key(scope, scope_id)
        lock = self._scope_lock(scope, scope_id)

        async with lock:
            subscribers = self._queues.get(key)
            if subscribers is None:
                return
            subscribers.pop(id(queue), None)
            if not subscribers:
                del self._queues[key]
