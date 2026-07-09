import asyncio
import json
import uuid
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
from app.api.deps import get_project_store
from app.api.runner import get_bridge
from app.projects import ProjectStore

router = APIRouter()


class MessageRequest(BaseModel):
    """A user message sent into an agent thread."""

    role: Literal["user", "assistant", "system"]
    content: str


class UpdatePlanRequest(BaseModel):
    """Request body for replacing the pending plan on a thread."""

    plan: Dict[str, Any]


def _agent_config(thread_id: str, app) -> Dict[str, Any]:
    """Build the RunnableConfig for a thread, including the api_key from app state."""
    api_key = getattr(app.state, "agent_api_keys", {}).get(thread_id, "")
    return {"configurable": {"thread_id": thread_id, "api_key": api_key}}


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


def _sync_payload(values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a client-safe payload from the current graph state values."""
    values = values or {}
    return {
        "messages": _render_messages(values),
        "interrupt_type": values.get("interrupt_type"),
        "operation_log": values.get("operation_log", []),
        "pending_plan": values.get("pending_plan"),
        "pending_command": values.get("pending_command"),
        "pending_script": values.get("pending_script"),
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
    """Run the graph with the supplied input and publish each value chunk."""
    app.state.active_agent_streams.add(thread_id)
    task = asyncio.current_task()
    app.state.pipeline_tasks.add(task)
    try:
        async for values in graph.astream(input_value, config, stream_mode="values"):
            payload = _sync_payload(values)
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
                "error": str(exc),
            },
        )
        raise
    finally:
        app.state.active_agent_streams.discard(thread_id)
        app.state.pipeline_tasks.discard(task)


def _start_stream(
    thread_id: str,
    graph,
    bridge,
    app,
    input_value: Any = None,
) -> None:
    """Launch a background task that streams graph values for a thread."""
    config = _agent_config(thread_id, app)
    asyncio.create_task(
        _stream_agent(thread_id, graph, config, bridge, app, input_value)
    )


@router.get("/", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def agent_root():
    return {"detail": "not implemented"}


@router.post("/threads", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def create_thread(
    request: Request,
    project_id: str = Query(..., description="Project to associate with the new thread"),
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Create a new agent thread and seed it with the project's initial state."""
    project = store.load_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在"
        )

    thread_id = str(uuid.uuid4())
    api_key = project.get("analysis", {}).get("api_key", "")
    request.app.state.agent_api_keys[thread_id] = api_key
    initial_state = build_initial_state(project)
    await graph.aupdate_state(_agent_config(thread_id, request.app), initial_state)
    return {"thread_id": thread_id}


@router.get("/threads/{thread_id}", response_model=Dict[str, Any])
async def get_thread(
    request: Request,
    thread_id: str,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """Return the current state for an agent thread."""
    try:
        snapshot = await graph.aget_state(_agent_config(thread_id, request.app))
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    payload = _sync_payload(snapshot.values)
    payload["thread_id"] = thread_id
    return payload


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
) -> Dict[str, Any]:
    """Append a user message to a thread and start streaming the agent response."""
    config = _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    message = _make_message(payload.role, payload.content)
    bridge = get_bridge(request)
    _start_stream(
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
    config = _agent_config(thread_id, request.app)
    try:
        await graph.aupdate_state(config, {"pending_plan": payload.plan})
        snapshot = await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    return _sync_payload(snapshot.values)


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
    config = _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    bridge = get_bridge(request)
    _start_stream(
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
    config = _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    bridge = get_bridge(request)
    _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        Command(resume={"action": "cancel"}),
    )
    return {"thread_id": thread_id}


@router.get("/threads/{thread_id}/events")
async def thread_events(
    thread_id: str,
    request: Request,
    last_event_id: int = Query(0, alias="last_event_id"),
    graph=Depends(get_agent_graph),
) -> StreamingResponse:
    """Stream agent events for a thread as server-sent events."""
    try:
        await graph.aget_state(_agent_config(thread_id, request.app))
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
