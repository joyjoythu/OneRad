import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.responses import StreamingResponse

from app.api.deps import get_project_store
from app.api.runner import get_bridge
from app.projects import ProjectStore

router = APIRouter()


@router.get("/{run_id}", response_model=Dict[str, Any])
def get_run(run_id: str, store: ProjectStore = Depends(get_project_store)) -> Dict[str, Any]:
    """Fetch a single run record by ID."""
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行记录不存在")
    return run


@router.get("/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    last_event_id: int = Query(0, alias="last_event_id"),
    store: ProjectStore = Depends(get_project_store),
) -> StreamingResponse:
    """Stream pipeline events for a run as server-sent events."""
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行记录不存在")

    bridge = get_bridge(request)

    async def event_generator():
        queue: asyncio.Queue = await bridge.subscribe(
            "run", run_id, last_event_id=last_event_id
        )
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    data = json.dumps(event["data"], ensure_ascii=False)
                    yield f"id: {event['event_id']}\nevent: pipeline\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    run = store.get_run(run_id)
                    if run is not None and run.get("status") != "running":
                        # Run has finished; flush any queued events before closing.
                        while not queue.empty():
                            event = queue.get_nowait()
                            data = json.dumps(event["data"], ensure_ascii=False)
                            yield f"id: {event['event_id']}\nevent: pipeline\ndata: {data}\n\n"
                        yield f": run {run['status']}\n\n"
                        break
                    yield ": keep-alive\n\n"
        finally:
            await bridge.unsubscribe("run", run_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
