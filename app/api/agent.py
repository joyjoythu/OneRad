import asyncio
import json
import uuid
from contextlib import suppress
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.types import Command
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.agent import build_initial_state, create_agent_graph
from app.agent import runtime as agent_runtime
from app.api.deps import get_project_store
from app.api.runner import get_bridge
from app.projects import ProjectStore

router = APIRouter()


class MessageRequest(BaseModel):
    """A user message sent into an agent thread."""

    role: Literal["user", "assistant", "system"]
    content: str


class CreateThreadRequest(BaseModel):
    """Request body for creating an agent thread."""

    api_key: str = ""
    llm_model: Literal["deepseek-v4-pro", "deepseek-v4-flash"] = "deepseek-v4-pro"


class UpdatePlanRequest(BaseModel):
    """Request body for replacing the pending plan on a thread."""

    plan: Dict[str, Any]


class ThreadPatchRequest(BaseModel):
    """Request body for renaming a thread."""

    title: str


class LoadThreadRequest(BaseModel):
    """Request body for resuming an existing thread."""

    api_key: str = ""
    llm_model: Literal["deepseek-v4-pro", "deepseek-v4-flash"] = "deepseek-v4-pro"


async def _run_store_sync(fn, *args):
    """Run a synchronous ProjectStore method in the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


async def _agent_config(thread_id: str, app) -> Dict[str, Any]:
    """Build the RunnableConfig for a thread.

    api_key and llm_model are normally set when the thread is created or
    resumed. If the server has restarted, fall back to the model stored in the
    threads table.
    """
    api_key = getattr(app.state, "agent_api_keys", {}).get(thread_id, "")
    llm_model = getattr(app.state, "agent_llm_models", {}).get(
        thread_id, ""
    )
    if not llm_model:
        store = getattr(app.state, "project_store", None)
        if store is not None:
            meta = await _run_store_sync(store.get_thread_meta, thread_id)
            llm_model = meta.get("llm_model", "deepseek-v4-pro") if meta else "deepseek-v4-pro"
    llm_model = llm_model or "deepseek-v4-pro"
    return {
        "configurable": {
            "thread_id": thread_id,
            "api_key": api_key,
            "llm_model": llm_model,
        }
    }


def _render_messages(values: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert LangChain message objects stored in state into plain dicts."""
    rendered: List[Dict[str, Any]] = []
    for msg in (values.get("messages") if values else None) or []:
        if isinstance(msg, dict):
            rendered.append(msg)
            continue

        if isinstance(msg, HumanMessage):
            entry = {"role": "user", "content": _stringify_content(msg.content)}
        elif isinstance(msg, AIMessage):
            entry = {"role": "assistant", "content": _stringify_content(msg.content)}
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = tool_calls
        elif isinstance(msg, ToolMessage):
            entry = {
                "role": "tool",
                "content": _stringify_content(msg.content),
                "tool_call_id": getattr(msg, "tool_call_id", ""),
            }
        elif isinstance(msg, SystemMessage):
            entry = {"role": "system", "content": _stringify_content(msg.content)}
        else:
            entry = {"role": "unknown", "content": _stringify_content(msg.content)}
        rendered.append(entry)
    return rendered


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


DEFAULT_CONTEXT_WINDOW = 1_000_000
MODEL_CONTEXT_WINDOWS = {
    "deepseek-v4-pro": 1_000_000,
    "deepseek-v4-flash": 1_000_000,
}


def _context_window_for_model(model: Optional[str]) -> int:
    """按模型名查上下文窗口大小，未知模型默认 1M。"""
    return MODEL_CONTEXT_WINDOWS.get(model or "", DEFAULT_CONTEXT_WINDOW)


def _sync_payload(values: Optional[Dict[str, Any]], running: bool) -> Dict[str, Any]:
    """Build a client-safe payload from the current graph state values.

    running 表示该线程当前是否有正在运行的流式任务。中间快照里的
    interrupt_type 可能滞后（如 human_review 完成后、execute_confirmed
    清除前），前端不能据此推断运行状态，必须以此字段为准。
    """
    values = values or {}
    return {
        "messages": _render_messages(values),
        "interrupt_type": values.get("interrupt_type"),
        "operation_log": values.get("operation_log", []),
        "pending_plan": values.get("pending_plan"),
        "pending_command": values.get("pending_command"),
        "pending_script": values.get("pending_script"),
        "pending_radiomics_plan": values.get("pending_radiomics_plan"),
        "pending_radiomics_execution": values.get("pending_radiomics_execution"),
        "pending_radiomics_analysis": values.get("pending_radiomics_analysis"),
        "context_usage": values.get("context_usage"),
        "context_window": _context_window_for_model(values.get("model")),
        "running": running,
    }


def _make_message(role: str, content: str) -> BaseMessage:
    if role == "user":
        return HumanMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content)
    if role == "system":
        return SystemMessage(content=content)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported message role: {role}",
    )


def _unanswered_tool_call_ids(messages: List[Any]) -> List[str]:
    """返回消息历史中没有对应 ToolMessage 应答的 tool_call id。

    停止运行后用于修复历史：为这些 id 各补一条 ToolMessage，
    避免下次调用 LLM 时报 400（tool_calls 缺少响应）。
    """
    answered = {
        getattr(msg, "tool_call_id", None)
        for msg in messages
        if isinstance(msg, ToolMessage)
    }
    missing: List[str] = []
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
            if tc_id and tc_id not in answered and tc_id not in missing:
                missing.append(tc_id)
    return missing


def get_agent_graph(request: Request):
    """Return the pre-compiled agent graph stored on app.state."""
    return request.app.state.agent_graph


async def _stream_agent(
    thread_id: str,
    graph,
    config: Dict[str, Any],
    bridge,
    app,
    input_value: Any = None,
) -> None:
    """Run the graph with the supplied input and publish each value chunk.

    调用方（_start_stream）负责在启动前标记线程忙碌，此处只在结束时清理。
    """
    task = asyncio.current_task()
    app.state.pipeline_tasks.add(task)
    try:
        async for values in graph.astream(input_value, config, stream_mode="values"):
            payload = _sync_payload(values, running=True)
            await bridge.publish("agent", thread_id, payload)
    except Exception as exc:
        await bridge.publish(
            "agent",
            thread_id,
            {
                "messages": [],
                "interrupt_type": None,
                "operation_log": [f"stream error: {exc}"],
                "pending_plan": None,
                "pending_command": None,
                "pending_script": None,
                "running": False,
                "error": str(exc),
            },
        )
        raise
    finally:
        app.state.active_agent_streams.discard(thread_id)
        app.state.pipeline_tasks.discard(task)
        app.state.agent_stream_tasks.pop(thread_id, None)
        agent_runtime.unregister(thread_id)


async def _start_stream(
    thread_id: str,
    graph,
    bridge,
    app,
    input_value: Any = None,
) -> None:
    """Launch a background task that streams graph values for a thread.

    原子地检查并标记线程忙碌（检查与标记之间无 await）。同一线程上已有
    运行中的流时抛出 409，避免并发运行交错写入检查点，导致 assistant 的
    tool_calls 后缺少对应 ToolMessage 而触发 LLM 400 错误。
    """
    if thread_id in app.state.active_agent_streams:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="智能体正在处理中，请等待当前任务完成后再试",
        )
    app.state.active_agent_streams.add(thread_id)
    # 登记运行时上下文：耗时节点（如特征提取）借此推送进度并响应 /stop 的取消。
    agent_runtime.register(thread_id, loop=asyncio.get_running_loop(), bridge=bridge)
    try:
        config = await _agent_config(thread_id, app)
        task = asyncio.create_task(
            _stream_agent(thread_id, graph, config, bridge, app, input_value)
        )
        app.state.agent_stream_tasks[thread_id] = task
    except Exception:
        app.state.active_agent_streams.discard(thread_id)
        agent_runtime.unregister(thread_id)
        raise


@router.get("", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def agent_root():
    return {"detail": "not implemented"}


@router.post("/threads", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def create_thread(
    request: Request,
    payload: Optional[CreateThreadRequest] = None,
    project_id: str = Query(..., description="Project to associate with the new thread"),
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Create a new agent thread and seed it with the project's initial state."""
    project = await _run_store_sync(store.load_project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在"
        )

    payload = payload or CreateThreadRequest()
    thread_id = str(uuid.uuid4())
    api_key = payload.api_key
    llm_model = payload.llm_model
    request.app.state.agent_api_keys[thread_id] = api_key
    request.app.state.agent_llm_models[thread_id] = llm_model
    initial_state = build_initial_state(project, api_key=api_key, llm_model=llm_model)
    await graph.aupdate_state(await _agent_config(thread_id, request.app), initial_state)
    await _run_store_sync(store.record_thread, project_id, thread_id, "", llm_model)
    return {"thread_id": thread_id}


@router.get("/threads/{thread_id}", response_model=Dict[str, Any])
async def get_thread(
    request: Request,
    thread_id: str,
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Return the current state for an agent thread."""
    if await _run_store_sync(store.get_thread_meta, thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    try:
        snapshot = await graph.aget_state(await _agent_config(thread_id, request.app))
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    payload = _sync_payload(
        snapshot.values,
        running=thread_id in request.app.state.active_agent_streams,
    )
    payload["thread_id"] = thread_id
    return payload


@router.get("/threads", response_model=Dict[str, Any])
async def list_threads(
    project_id: str = Query(..., description="Project to list threads for"),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Return all threads belonging to a project."""
    return {"threads": await _run_store_sync(store.list_threads, project_id)}


@router.delete(
    "/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_thread(
    thread_id: str,
    request: Request,
    store: ProjectStore = Depends(get_project_store),
) -> None:
    """Delete a thread and all associated checkpoints/events."""
    if await _run_store_sync(store.get_thread_meta, thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    checkpointer = request.app.state.checkpointer
    try:
        await checkpointer.adelete_thread(thread_id)
        await _run_store_sync(store.delete_thread, thread_id)
        request.app.state.agent_api_keys.pop(thread_id, None)
        request.app.state.agent_llm_models.pop(thread_id, None)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to delete thread",
        ) from exc
    return None


@router.patch("/threads/{thread_id}", response_model=Dict[str, Any])
async def patch_thread(
    thread_id: str,
    payload: ThreadPatchRequest,
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Rename a thread."""
    if await _run_store_sync(store.get_thread_meta, thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    updated = await _run_store_sync(store.update_thread_title, thread_id, payload.title)
    return {"thread": updated}


@router.post("/threads/{thread_id}/resume", response_model=Dict[str, Any])
async def resume_thread(
    request: Request,
    thread_id: str,
    payload: LoadThreadRequest,
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Resume an existing thread, refreshing api_key/llm_model in memory."""
    if await _run_store_sync(store.get_thread_meta, thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    request.app.state.agent_api_keys[thread_id] = payload.api_key
    request.app.state.agent_llm_models[thread_id] = payload.llm_model
    snapshot = await graph.aget_state(await _agent_config(thread_id, request.app))
    payload_out = _sync_payload(
        snapshot.values,
        running=thread_id in request.app.state.active_agent_streams,
    )
    payload_out["thread_id"] = thread_id
    return payload_out


@router.post(
    "/threads/{thread_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def send_message(
    thread_id: str,
    payload: MessageRequest,
    request: Request,
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Append a user message to a thread and start streaming the agent response."""
    config = await _agent_config(thread_id, request.app)
    try:
        snapshot = await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    # 快速失败：避免在明显不可发送时仍更新会话标题/时间戳。
    # 并发的兜底校验在 _start_stream 中（检查与标记之间无 await）。
    if thread_id in request.app.state.active_agent_streams:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="智能体正在处理上一条消息，请等待其完成后再发送",
        )
    if snapshot.values.get("interrupt_type"):
        # 中断等待确认时，消息历史末尾是尚无 ToolMessage 的 tool_calls，
        # 直接追加新消息会让 LLM 返回 400。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前存在待确认的操作，请先确认或取消后再发送新消息",
        )

    message = _make_message(payload.role, payload.content)
    await _run_store_sync(store.update_thread_timestamp, thread_id)
    if payload.role == "user":
        meta = await _run_store_sync(store.get_thread_meta, thread_id)
        if meta and not meta.get("title"):
            title = payload.content[:30] if payload.content else ""
            await _run_store_sync(store.update_thread_title, thread_id, title)

    bridge = get_bridge(request)
    await _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        {"messages": [message]},
    )
    return {"thread_id": thread_id}


@router.put("/threads/{thread_id}/plan", response_model=Dict[str, Any])
async def update_plan(
    request: Request,
    thread_id: str,
    payload: UpdatePlanRequest,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """Update the pending plan on a thread without running the graph."""
    config = await _agent_config(thread_id, request.app)
    try:
        await graph.aupdate_state(config, {"pending_plan": payload.plan})
        snapshot = await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    return _sync_payload(
        snapshot.values,
        running=thread_id in request.app.state.active_agent_streams,
    )


@router.post(
    "/threads/{thread_id}/confirm",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def confirm_interrupt(
    thread_id: str,
    request: Request,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """Resume a thread waiting on an interrupt with a confirmation."""
    config = await _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    bridge = get_bridge(request)
    await _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        Command(resume={"action": "confirm"}),
    )
    return {"thread_id": thread_id}


@router.post(
    "/threads/{thread_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def cancel_interrupt(
    thread_id: str,
    request: Request,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """Resume a thread waiting on an interrupt with a cancellation."""
    config = await _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    bridge = get_bridge(request)
    await _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        Command(resume={"action": "cancel"}),
    )
    return {"thread_id": thread_id}


@router.post(
    "/threads/{thread_id}/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def stop_stream(
    thread_id: str,
    request: Request,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """停止线程上正在运行的智能体流式任务，保留对话上下文。

    取消后台任务后，若消息历史末尾仍有未应答的 tool_calls，为每个缺失的
    tool_call_id 补一条「已停止」ToolMessage，避免下次调用 LLM 时因
    tool_calls 缺少响应而报 400。
    """
    config = await _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    task = request.app.state.agent_stream_tasks.get(thread_id)
    if thread_id not in request.app.state.active_agent_streams or task is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前没有正在运行的任务",
        )

    # 先通知耗时任务（如特征提取的工作线程）在下一个检查点退出，
    # 再取消 asyncio 流式任务——线程无法被强杀，必须协作式取消。
    agent_runtime.request_cancel(thread_id)
    task.cancel()
    # 等待任务收尾（finally 清理集合与映射）。任务若已因其他异常结束，
    # 错误已由 _stream_agent 发布，这里不重复抛出。
    with suppress(asyncio.CancelledError, Exception):
        await task

    snapshot = await graph.aget_state(config)
    missing_ids = _unanswered_tool_call_ids(snapshot.values.get("messages", []))
    if missing_ids:
        await graph.aupdate_state(
            config,
            {
                "messages": [
                    ToolMessage(
                        content=json.dumps(
                            {"cancelled": True, "reason": "用户停止了操作"},
                            ensure_ascii=False,
                        ),
                        tool_call_id=tc_id,
                    )
                    for tc_id in missing_ids
                ],
                "operation_log": ["用户停止了当前任务"],
            },
        )
        snapshot = await graph.aget_state(config)

    bridge = get_bridge(request)
    await bridge.publish(
        "agent", thread_id, _sync_payload(snapshot.values, running=False)
    )
    return {"thread_id": thread_id, "status": "stopped"}


@router.get("/threads/{thread_id}/events")
async def thread_events(
    thread_id: str,
    request: Request,
    last_event_id: int = Query(0, alias="last_event_id"),
    graph=Depends(get_agent_graph),
) -> StreamingResponse:
    """Stream agent events for a thread as server-sent events."""
    try:
        await graph.aget_state(await _agent_config(thread_id, request.app))
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    bridge = get_bridge(request)

    async def event_generator():
        queue: asyncio.Queue = await bridge.subscribe(
            "agent", thread_id, last_event_id=last_event_id
        )
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    data = json.dumps(event["data"], ensure_ascii=False)
                    yield f"id: {event['event_id']}\nevent: agent\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    if thread_id not in request.app.state.active_agent_streams:
                        yield "event: agent_end\ndata: {}\n\n"
                        break
                    yield ": keep-alive\n\n"
        finally:
            await bridge.unsubscribe("agent", thread_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
