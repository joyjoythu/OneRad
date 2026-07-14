import asyncio
import json
import logging
import traceback
from typing import Any, Dict

from fastapi import Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.sse import EventBridge
from app.orchestrator import Orchestrator, register_default_handlers
from app.projects import ProjectStore
from app.utils import parse_covariates

logger = logging.getLogger(__name__)


class RunConfig(BaseModel):
    """Analysis configuration submitted when triggering a pipeline run."""

    image_dir: str = ""
    clinical_path: str = ""
    output_dir: str = "./outputs"
    modality: str = "auto"
    covariates: str = ""
    model: str = "logistic"
    analysis_model: str = "logistic"
    llm_model: str = "deepseek-v4-pro"
    api_key: str = ""


def get_bridge(request: Request) -> EventBridge:
    """Return the application-level EventBridge stored on app.state."""
    return request.app.state.event_bridge


def publish_event(
    bridge: EventBridge,
    loop: asyncio.AbstractEventLoop,
    run_id: str,
    data: Dict[str, Any],
    wait: bool = False,
) -> None:
    """Publish an event from a threadpool worker to the main event loop.

    If the event loop is no longer running, the publish is skipped to avoid
    leaking an unawaited coroutine during application shutdown.
    """
    if loop.is_closed() or not loop.is_running():
        return
    try:
        future = asyncio.run_coroutine_threadsafe(
            bridge.publish("run", run_id, data), loop
        )
        if wait:
            future.result(timeout=5)
    except Exception:
        logger.exception("Failed to publish event for run %s", run_id)


def _is_cancelled(store: ProjectStore, run_id: str) -> bool:
    run = store.get_run(run_id)
    return run is not None and run.get("status") == "cancelled"


def run_pipeline(
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
        publish_event(
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
            model=config.get("analysis_model") or config.get("model", "logistic"),
            llm_model=config.get("llm_model", "deepseek-v4-pro"),
            api_key=config.get("api_key"),
        )
        register_default_handlers(orch)

        def emit(event: Dict[str, Any]) -> None:
            publish_event(bridge, loop, run_id, event, wait=True)

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

        if _is_cancelled(store, run_id):
            run_status = "cancelled"
            log_summary = "用户取消"
        store.record_run_end(run_id, run_status, log_summary, report_path)
    except Exception as exc:
        if _is_cancelled(store, run_id):
            return
        tb = traceback.format_exc()
        error_event = {"type": "pipeline_error", "message": str(exc), "traceback": tb}
        publish_event(bridge, loop, run_id, error_event)
        store.record_run_end(run_id, "failed", f"{exc}\n{tb}")


def start_pipeline_task(
    app,
    project_id: str,
    run_id: str,
    config: Dict[str, Any],
    bridge: EventBridge,
    store: ProjectStore,
    loop: asyncio.AbstractEventLoop,
) -> asyncio.Task:
    """Launch a tracked background task that runs the pipeline."""

    async def _tracked_run() -> None:
        task = asyncio.current_task()
        app.state.pipeline_tasks.add(task)
        app.state.pipeline_task_map[run_id] = task
        try:
            await run_in_threadpool(
                run_pipeline,
                project_id,
                run_id,
                config,
                bridge,
                store,
                loop,
            )
        except asyncio.CancelledError:
            try:
                await bridge.publish(
                    "run", run_id, {"type": "pipeline_cancelled", "message": "用户取消运行"}
                )
            except Exception:
                logger.exception("Failed to publish cancellation event for run %s", run_id)
            store.record_run_end(run_id, "cancelled", "用户取消")
            raise
        finally:
            app.state.pipeline_tasks.discard(task)
            app.state.pipeline_task_map.pop(run_id, None)

    return asyncio.create_task(_tracked_run())
