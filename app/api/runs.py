import asyncio
import json
import traceback
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.api.deps import get_project_store
from app.api.sse import EventBridge
from app.orchestrator import Orchestrator, register_default_handlers
from app.projects import ProjectStore
from app.utils import parse_covariates

router = APIRouter()


class RunConfig(BaseModel):
    """Analysis configuration submitted when triggering a pipeline run."""

    image_dir: str = ""
    clinical_path: str = ""
    output_dir: str = "./outputs"
    modality: str = "auto"
    covariates: str = ""
    model: str = "deepseek-v4-pro"
    api_key: str = ""


_bridges: Dict[str, EventBridge] = {}


def _get_bridge(store: ProjectStore) -> EventBridge:
    """Return a module-level EventBridge singleton keyed by the store's DB path."""
    key = str(store.db_path)
    if key not in _bridges:
        _bridges[key] = EventBridge(key)
    return _bridges[key]


def _publish_event(
    bridge: EventBridge,
    loop: asyncio.AbstractEventLoop,
    run_id: str,
    data: Dict[str, Any],
    wait: bool = False,
) -> None:
    """Publish an event from a threadpool worker to the main event loop.

    If the event loop is no longer running, the publish is skipped silently to
    avoid leaking an unawaited coroutine during application shutdown.
    """
    if loop.is_closed() or not loop.is_running():
        return
    try:
        future = asyncio.run_coroutine_threadsafe(
            bridge.publish("run", run_id, data), loop
        )
        if wait:
            future.result(timeout=10)
    except Exception:
        pass


def _run_pipeline(
    project_id: str,
    run_id: str,
    config: Dict[str, Any],
    bridge: EventBridge,
    store: ProjectStore,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Execute the radiomics pipeline in a threadpool and record the outcome.

    Events emitted by the orchestrator are published to the EventBridge so that
    SSE subscribers can stream them in real time. Exceptions are caught, emitted
    as error events, and recorded as a failed run.
    """
    project = store.load_project(project_id)
    if project is None:
        _publish_event(
            bridge, loop, run_id, {"type": "pipeline_error", "message": "项目不存在"}
        )
        store.record_run_end(run_id, "failed", "项目不存在")
        return

    try:
        orch = Orchestrator(
            image_dir=config.get("image_dir", ""),
            clinical_path=config.get("clinical_path", ""),
            output_dir=config.get("output_dir", "./outputs"),
            modality=config.get("modality", "auto"),
            covariates=parse_covariates(config.get("covariates", "")),
            model=config.get("model", "deepseek-v4-pro"),
            api_key=config.get("api_key"),
        )
        register_default_handlers(orch)

        def emit(event: Dict[str, Any]) -> None:
            _publish_event(bridge, loop, run_id, event, wait=True)

        orch.set_sse_emitter(emit)

        # Drive the pipeline generator. Each yielded event is emitted via SSE.
        for _ in orch.run():
            pass

        final_stage = orch.state.get("stage")
        run_status = (
            "failed"
            if final_stage is not None and final_stage.name == "FAILED"
            else "completed"
        )

        report_path = ""
        report_state = orch.state.get("report")
        if isinstance(report_state, dict):
            report_path = report_state.get("report_path") or report_state.get("path") or ""

        error_log = orch.state.get("error_log", [])
        log_summary = "\n".join(str(entry) for entry in error_log)

        store.record_run_end(run_id, run_status, log_summary, report_path)
    except Exception as exc:
        tb = traceback.format_exc()
        error_event = {"type": "pipeline_error", "message": str(exc), "traceback": tb}
        _publish_event(bridge, loop, run_id, error_event)
        store.record_run_end(run_id, "failed", f"{exc}\n{tb}")


@router.post(
    "/projects/{project_id}/runs",
    response_model=Dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    project_id: str,
    payload: RunConfig,
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Trigger a new pipeline run for a project."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    if store.has_running_run(project_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="项目已有正在运行的流水线"
        )

    run_id = store.record_run_start(project_id, payload.model_dump())
    bridge = _get_bridge(store)
    loop = asyncio.get_running_loop()

    asyncio.create_task(
        run_in_threadpool(
            _run_pipeline,
            project_id,
            run_id,
            payload.model_dump(),
            bridge,
            store,
            loop,
        )
    )

    return {"run_id": run_id}


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
    last_event_id: int = Query(0, alias="last_event_id"),
    store: ProjectStore = Depends(get_project_store),
) -> StreamingResponse:
    """Stream pipeline events for a run as server-sent events."""
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行记录不存在")

    bridge = _get_bridge(store)

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
                        # Run has finished; no further events will be produced.
                        yield f": run {run['status']}\n\n"
                        break
                    yield ": keep-alive\n\n"
        finally:
            await bridge.unsubscribe("run", run_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
