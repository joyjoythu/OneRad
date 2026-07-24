import asyncio
import json
import logging
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.errors import InvalidUpdateError
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.agent import build_initial_state, create_agent_graph
from app.agent import runtime as agent_runtime
from app.api.deps import get_general_settings_store, get_project_store
from app.api.runner import get_bridge
from app.constants import DEEPSEEK_MODELS
from app.conversation_export import export_conversation
from app.llm import LLMClient, build_thread_title_prompt
from app.projects import ProjectStore
from app.settings import GeneralSettingsStore
from app.skills import SkillLoadError

router = APIRouter()

logger = logging.getLogger(__name__)


class MessageRequest(BaseModel):
    """A user message sent into an agent thread."""

    role: Literal["user", "assistant", "system"]
    content: str
    # 本次运行使用的模型；缺省时沿用会话上次的选择。
    model: Optional[str] = None


class CreateThreadRequest(BaseModel):
    """Request body for creating an agent thread."""

    model_config = ConfigDict(extra="forbid")

    auto_approve: bool = False


class UpdatePlanRequest(BaseModel):
    """Request body for replacing the pending plan on a thread."""

    plan: Dict[str, Any]


class AutoApproveRequest(BaseModel):
    """Request body for toggling auto-approve on a thread."""

    enabled: bool


class OtherRequest(BaseModel):
    """Request body for resuming an interrupt with a custom instruction."""

    instruction: str


class AnswerRequest(BaseModel):
    """Request body for resuming a user_choice interrupt with the chosen answer."""

    answer: str


class ExportRequest(BaseModel):
    """Request body for exporting a conversation."""

    format: Literal["md", "docx"] = "md"


class ThreadPatchRequest(BaseModel):
    """Request body for renaming a thread."""

    title: str


class LoadThreadRequest(BaseModel):
    """Request body for resuming an existing thread."""

    model_config = ConfigDict(extra="forbid")

    auto_approve: bool = False


async def _run_store_sync(fn, *args):
    """Run a synchronous ProjectStore method in the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _schedule_title_generation(app, thread_id: str, content: str) -> None:
    """后台为首次对话生成摘要标题，不阻塞消息响应。"""
    system, user = build_thread_title_prompt(content)
    task = asyncio.create_task(
        _generate_thread_title(app, thread_id, content, system, user)
    )
    app.state.agent_title_tasks.add(task)
    task.add_done_callback(app.state.agent_title_tasks.discard)


async def _generate_thread_title(
    app, thread_id: str, content: str, system: str, user: str
) -> None:
    """用 LLM 概括首条消息作为会话标题；失败时回退为首句截断。"""
    store: ProjectStore = app.state.project_store
    api_key = app.state.agent_api_keys.get(thread_id, "")
    title = ""
    try:
        client = LLMClient(api_key=api_key)
        # max_tokens 需要余量：推理模型（如 deepseek-v4-flash）会先消耗
        # reasoning tokens，额度太小会导致 content 为空、静默落入截断兜底。
        raw = await asyncio.to_thread(client.call, system, user, 0.3, 200)
        # 只取首行并去掉引号/结尾标点，防止模型输出格式漂移
        title = raw.splitlines()[0].strip().strip("\"'。！？!?.…") if raw else ""
    except Exception:
        logger.warning("生成会话标题失败，回退为截断命名", exc_info=True)
    if not title:
        logger.warning("LLM 返回空标题，回退为截断命名（thread_id=%s）", thread_id)
        title = content[:30]
    if not title:
        return
    # 用户可能在生成期间已手动改名：只覆盖仍为空的标题。
    meta = await _run_store_sync(store.get_thread_meta, thread_id)
    if meta and not meta.get("title"):
        await _run_store_sync(store.update_thread_title, thread_id, title)


async def _agent_config(thread_id: str, app) -> Dict[str, Any]:
    """Build the RunnableConfig for a thread.

    The API key is refreshed when the thread is created or resumed. The model
    comes from the thread's checkpointed state (updated per message request);
    unsupported legacy values fall back to the default model in nodes.
    """
    api_key = getattr(app.state, "agent_api_keys", {}).get(thread_id, "")
    return {
        "configurable": {
            "thread_id": thread_id,
            "api_key": api_key,
            "auto_approve": getattr(app.state, "agent_auto_approve", {}).get(
                thread_id, False
            ),
        }
    }


def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串，用于消息时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _log_entry(text: str) -> Dict[str, str]:
    """操作日志条目：记录写入时间，供前端展示。"""
    return {"time": _utc_now_iso(), "text": text}


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
            reasoning = msg.additional_kwargs.get("reasoning_content")
            if reasoning:
                entry["reasoning_content"] = reasoning
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
        ts = msg.additional_kwargs.get("timestamp")
        if ts:
            entry["timestamp"] = ts
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


def _context_window_for_model(model: Optional[str]) -> int:
    """Return the fixed model's context window; legacy state is ignored."""
    return DEFAULT_CONTEXT_WINDOW


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
        "pending_feature_statistics": values.get("pending_feature_statistics"),
        "pending_subagent": values.get("pending_subagent"),
        "pending_choice": values.get("pending_choice"),
        "context_usage": values.get("context_usage"),
        "todos": values.get("todos") or [],
        "context_window": _context_window_for_model(values.get("model")),
        "running": running,
    }


def _make_message(role: str, content: str) -> BaseMessage:
    kwargs = {"timestamp": _utc_now_iso()}
    if role == "user":
        return HumanMessage(content=content, additional_kwargs=kwargs)
    if role == "assistant":
        return AIMessage(content=content, additional_kwargs=kwargs)
    if role == "system":
        return SystemMessage(content=content, additional_kwargs=kwargs)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported message role: {role}",
    )


async def _aupdate_state_preserving_resume(
    graph, config: Dict[str, Any], values: Dict[str, Any]
) -> None:
    """写回 graph state：优先裸更新，保留 interrupt 恢复语义。

    显式 as_node 会把更新伪装成该节点的写入，使 interrupt 处挂起的任务被
    跳过，confirm/cancel 恢复静默失效。裸更新让 langgraph 依据 checkpoint
    的 versions_seen 推断归属；仅对未经任何节点执行的 input-only
    checkpoint（不可能有挂起中断）裸更新抛 InvalidUpdateError，此时回退
    显式 as_node="__start__"：其 writer 是纯 ChannelWrite，不执行任何
    分支函数（as_node="call_llm" 会连带执行 should_continue，在空消息
    历史上 IndexError），且触发痕迹与 create_thread 的播种写入一致。
    """
    try:
        await graph.aupdate_state(config, values)
    except InvalidUpdateError:
        await graph.aupdate_state(config, values, as_node="__start__")


async def _ensure_message_timestamps(graph, config: Dict[str, Any]) -> None:
    """为 state 中缺少 timestamp 的消息补打当前 UTC 时间并写回 checkpoint。

    AI/工具消息由图内部节点在运行期间产生，无法在创建点逐个打标；
    在运行收尾等收敛点统一补打，保证刷新/重启后历史消息时间仍准确。
    已有 timestamp 的消息不改写。
    """
    try:
        snapshot = await graph.aget_state(config)
    except KeyError:
        return
    messages = snapshot.values.get("messages") or []
    changed = False
    # AsyncSqliteSaver 返回反序列化副本，原地修改安全；即使后续写回失败，
    # 补打也是幂等的，重新执行无副作用。
    for msg in messages:
        if isinstance(msg, dict):
            continue
        kwargs = getattr(msg, "additional_kwargs", None)
        if kwargs is not None and not kwargs.get("timestamp"):
            kwargs["timestamp"] = _utc_now_iso()
            changed = True
    if changed:
        await _aupdate_state_preserving_resume(
            graph, config, {"messages": list(messages)}
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


async def _maybe_extract_memories(
    thread_id: str, graph, config: Dict[str, Any], app
) -> None:
    """在流式运行正常结束后，用 LLM 从本轮对话中提取长期记忆。

    仅当有 API key 且 state 中存在 project_id 时才执行；失败静默跳过，
    不影响正常消息响应。
    """
    try:
        snapshot = await graph.aget_state(config)
        values = snapshot.values if snapshot else None
        if not values:
            return
        project_id = values.get("project_id", "")
        if not project_id:
            return
        api_key = getattr(app.state, "agent_api_keys", {}).get(thread_id, "")
        if not api_key:
            return
        messages = _render_messages(values)
        if not messages:
            return
        # 检查全局记忆开关，避免在记忆关闭时白白调用 LLM 提取
        settings_store = getattr(app.state, "settings_store", None)
        if settings_store is not None and not settings_store.is_memory_enabled():
            logger.debug("记忆功能已关闭，跳过提取 thread_id=%s", thread_id)
            return
        from app.agent.memory import extract_memories
        from app.llm import LLMClient

        llm_client = LLMClient(api_key=api_key)
        memories = await asyncio.to_thread(
            extract_memories, messages, llm_client
        )
        if not memories:
            return
        store = app.state.project_store
        inserted = await asyncio.to_thread(
            store.add_memories, project_id, memories
        )
        if inserted:
            logger.info(
                "长期记忆已提取 thread_id=%s project_id=%s inserted=%d",
                thread_id, project_id, inserted,
            )
    except Exception:
        logger.warning("长期记忆提取失败 thread_id=%s", thread_id, exc_info=True)


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
    errored = False
    try:
        async for values in graph.astream(input_value, config, stream_mode="values"):
            payload = _sync_payload(values, running=True)
            await bridge.publish("agent", thread_id, payload)
    except Exception as exc:
        errored = True
        await bridge.publish(
            "agent",
            thread_id,
            {
                "messages": [],
                "interrupt_type": None,
                "operation_log": [_log_entry(f"stream error: {exc}")],
                "pending_plan": None,
                "pending_command": None,
                "pending_script": None,
                "running": False,
                "error": str(exc),
            },
        )
        raise
    finally:
        # 运行收尾（正常/异常/取消）统一补打本轮新消息的时间戳。
        # 内层 finally 保证清理无条件执行：补打期间被再次取消
        # （CancelledError 不受 suppress(Exception) 拦截）也不会跳过清理。
        try:
            with suppress(Exception):
                await _ensure_message_timestamps(graph, config)
            # 正常结束后提取长期记忆（异常/取消不提取）
            if not errored:
                with suppress(Exception):
                    await _maybe_extract_memories(thread_id, graph, config, app)
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
    settings_store: GeneralSettingsStore = Depends(get_general_settings_store),
) -> Dict[str, Any]:
    """Create a new agent thread and seed it with the project's initial state."""
    project = await _run_store_sync(store.load_project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在"
        )

    payload = payload or CreateThreadRequest()
    thread_id = str(uuid.uuid4())
    api_key = settings_store.resolve_api_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="尚未配置 DeepSeek API 密钥",
        )
    request.app.state.agent_api_keys[thread_id] = api_key
    request.app.state.agent_auto_approve[thread_id] = payload.auto_approve
    initial_state = build_initial_state(project)
    await graph.aupdate_state(await _agent_config(thread_id, request.app), initial_state)
    await _run_store_sync(store.record_thread, project_id, thread_id, "")
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
    request: Request,
    project_id: str = Query(..., description="Project to list threads for"),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Return all threads belonging to a project.

    每个线程附带 running 标志：该线程当前是否有正在运行的流式任务，
    供侧边栏展示运行状态（来源为内存集合，重启即清，与任务生命周期一致）。
    """
    threads = await _run_store_sync(store.list_threads, project_id)
    active = request.app.state.active_agent_streams
    for thread in threads:
        thread.pop("llm_model", None)
        thread["running"] = thread["id"] in active
    return {"threads": threads}


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
    # 删除前必须先停掉仍在运行的流式任务：先置位取消事件让耗时任务
    # （如特征提取的工作线程）协作式退出，再取消 asyncio 流式任务并等其收尾。
    # 否则删除后提取仍在后台继续，运行中的任务还会写已删除的 checkpoint。
    cancelled = agent_runtime.request_cancel(thread_id)
    if cancelled:
        logger.info("delete_thread: 已请求取消运行中任务 thread_id=%s", thread_id)
    task = request.app.state.agent_stream_tasks.get(thread_id)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
    checkpointer = request.app.state.checkpointer
    try:
        await checkpointer.adelete_thread(thread_id)
        await _run_store_sync(store.delete_thread, thread_id)
        request.app.state.agent_api_keys.pop(thread_id, None)
        request.app.state.agent_auto_approve.pop(thread_id, None)
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
    if updated:
        updated.pop("llm_model", None)
    return {"thread": updated}


@router.post("/threads/{thread_id}/resume", response_model=Dict[str, Any])
async def resume_thread(
    request: Request,
    thread_id: str,
    payload: LoadThreadRequest,
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
    settings_store: GeneralSettingsStore = Depends(get_general_settings_store),
) -> Dict[str, Any]:
    """Resume an existing thread, refreshing its API key in memory."""
    if await _run_store_sync(store.get_thread_meta, thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    request.app.state.agent_api_keys[thread_id] = settings_store.resolve_api_key()
    request.app.state.agent_auto_approve[thread_id] = payload.auto_approve
    snapshot = await graph.aget_state(await _agent_config(thread_id, request.app))
    payload_out = _sync_payload(
        snapshot.values,
        running=thread_id in request.app.state.active_agent_streams,
    )
    payload_out["thread_id"] = thread_id
    return payload_out


@router.put("/threads/{thread_id}/auto-approve", response_model=Dict[str, Any])
async def set_auto_approve(
    thread_id: str,
    payload: AutoApproveRequest,
    request: Request,
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Toggle auto-approve for a thread; applies from the next graph run."""
    if await _run_store_sync(store.get_thread_meta, thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    request.app.state.agent_auto_approve[thread_id] = payload.enabled
    return {"auto_approve": payload.enabled}


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
    if payload.model is not None and payload.model not in DEEPSEEK_MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的模型：{payload.model}",
        )
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
            if request.app.state.agent_api_keys.get(thread_id):
                try:
                    _schedule_title_generation(
                        request.app, thread_id, payload.content or ""
                    )
                except SkillLoadError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=str(exc),
                    ) from exc
            else:
                # 无 API key 时回退为首句截断命名
                title = payload.content[:30] if payload.content else ""
                await _run_store_sync(store.update_thread_title, thread_id, title)

    bridge = get_bridge(request)
    # 携带模型选择时写入 state 并随检查点持久化，后续消息缺省沿用。
    stream_input: Dict[str, Any] = {"messages": [message]}
    if payload.model:
        stream_input["model"] = payload.model
    await _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        stream_input,
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
        await _aupdate_state_preserving_resume(
            graph, config, {"pending_plan": payload.plan}
        )
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
    "/threads/{thread_id}/other",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def other_interrupt(
    thread_id: str,
    payload: OtherRequest,
    request: Request,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """Resume a thread waiting on an interrupt: cancel the pending call and
    pass the user's custom instruction on to the agent."""
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="instruction 不能为空",
        )

    config = await _agent_config(thread_id, request.app)
    try:
        snapshot = await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    if not snapshot.values.get("interrupt_type"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前没有待确认的操作",
        )

    bridge = get_bridge(request)
    await _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        Command(resume={"action": "other", "instruction": instruction}),
    )
    return {"thread_id": thread_id}


@router.post(
    "/threads/{thread_id}/answer",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def answer_interrupt(
    thread_id: str,
    payload: AnswerRequest,
    request: Request,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """Resume a user_choice interrupt: 把用户在选择面板中提交的答案
    作为提问工具的结果返回给 agent。"""
    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="answer 不能为空",
        )

    config = await _agent_config(thread_id, request.app)
    try:
        snapshot = await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    if snapshot.values.get("interrupt_type") != "user_choice":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前没有待回答的选择提问",
        )

    bridge = get_bridge(request)
    await _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        Command(resume={"action": "answer", "answer": answer}),
    )
    return {"thread_id": thread_id}


@router.post(
    "/threads/{thread_id}/export",
    response_model=Dict[str, Any],
)
async def export_thread(
    thread_id: str,
    payload: ExportRequest,
    request: Request,
    store: ProjectStore = Depends(get_project_store),
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """把当前会话导出为 Markdown/Word 文档，写入项目目录 conversation_exports/。"""
    config = await _agent_config(thread_id, request.app)
    try:
        snapshot = await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    values = snapshot.values or {}
    messages = _render_messages(values)
    if not any(m.get("role") in ("user", "assistant") for m in messages):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前对话没有可导出的内容",
        )
    project_path = values.get("project_path")
    if not project_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少项目路径，无法导出",
        )

    meta = await _run_store_sync(store.get_thread_meta, thread_id)
    title = (meta or {}).get("title") or "未命名对话"
    path = await run_in_threadpool(
        export_conversation, project_path, title, messages, payload.format
    )
    logger.info("会话已导出 thread_id=%s path=%s", thread_id, path)
    return {"path": str(path), "format": payload.format}


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

    # 先通知耗时任务（如特征提取的工作线程）在下一个检查点退出，
    # 再取消 asyncio 流式任务——线程无法被强杀，必须协作式取消。
    # 注意：cancel_event 的置位必须优先于任何可能失败的检查，
    # 否则 409 响应会让前端解除 busy 状态，但工作线程永远收不到取消信号。
    cancelled = agent_runtime.request_cancel(thread_id)
    logger.info(
        "收到 /stop 请求 thread_id=%s cancel_ack=%s", thread_id, cancelled
    )

    task = request.app.state.agent_stream_tasks.get(thread_id)
    if thread_id not in request.app.state.active_agent_streams or task is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前没有正在运行的任务",
        )

    task.cancel()
    # 等待任务收尾（finally 清理集合与映射）。任务若已因其他异常结束，
    # 错误已由 _stream_agent 发布，这里不重复抛出。
    with suppress(asyncio.CancelledError, Exception):
        await task

    snapshot = await graph.aget_state(config)
    # 取消 asyncio 流式任务后，执行中节点（如 execute_confirmed 在
    # 线程池里跑 FeatureAgent）的返回值会因 async generator 已销毁而丢失，
    # checkpoint 里仍保留着旧的 interrupt_type 与 pending 字段。
    # 前端收到 running=false 时若 interrupt_type 仍非空会重新弹出审批面板，
    # 因此必须在 checkpoint 中显式清除中断状态。
    current_interrupt = snapshot.values.get("interrupt_type") if snapshot.values else None
    if current_interrupt:
        logger.info(
            "/stop: 清除残留 interrupt_type=%s thread_id=%s",
            current_interrupt, thread_id,
        )
        await graph.aupdate_state(
            config,
            {
                "interrupt_type": None,
                "pending_plan": None,
                "pending_command": None,
                "pending_script": None,
                "pending_radiomics_plan": None,
                "pending_radiomics_execution": None,
                "pending_radiomics_analysis": None,
                "pending_feature_statistics": None,
                "pending_subagent": None,
                "pending_choice": None,
                "choice_answer": None,
                "script_risk_level": None,
                "confirmed": None,
                "other_instruction": None,
                "operation_log": [_log_entry("用户停止了当前任务")],
            },
        )
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
                "operation_log": [_log_entry("用户停止了当前任务")],
            },
        )
        # 补打同样是 best-effort：失败不应把已成功的 stop 变成 500
        with suppress(Exception):
            await _ensure_message_timestamps(graph, config)
        snapshot = await graph.aget_state(config)

    # 计划面板里仍在进行的步骤定格为「已停止」（仿子任务面板的
    # running→cancelled 定格）：否则刷新/重连后前端仍按 in_progress
    # 渲染，计划面板会一直显示运行中动画。只在确有 in_progress 步骤时
    # 追加一次状态更新，不影响无计划面板场景的快照读取次数。
    todos = snapshot.values.get("todos") if snapshot.values else None
    if todos and any(t.get("status") == "in_progress" for t in todos):
        await graph.aupdate_state(
            config,
            {
                "todos": [
                    {**t, "status": "cancelled"}
                    if isinstance(t, dict) and t.get("status") == "in_progress"
                    else t
                    for t in todos
                ]
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
    last_event_id: Optional[int] = Query(None, alias="last_event_id"),
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

    # 默认只订阅新事件：当前完整状态由 resume/get 接口返回，全量回放历史
    # 快照会让前端把过期中间状态逐个重放（长历史时界面从头滚动加载）。
    # 仅显式传 last_event_id（或 EventSource 自动重连携带 Last-Event-ID 头）
    # 时才回放其后的历史事件。
    fresh_subscribe = last_event_id is None
    if last_event_id is None:
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            last_event_id = int(header)
            fresh_subscribe = False
    if last_event_id is None:
        last_event_id = await bridge.next_event_id("agent", thread_id) - 1

    # 页面刷新后的全新订阅不回放历史，但影像组学提取进度只走旁路事件、
    # 不在 state 快照里：线程仍在运行时补偿推送最近一次进度，否则前端
    # 进度条在刷新后消失。补偿事件不带 id 行：EventSource 的 Last-Event-ID
    # 保持未设置，浏览器自动重连时重新走本补偿逻辑而非回放全部历史。
    catch_up_data: Optional[str] = None
    if fresh_subscribe and thread_id in request.app.state.active_agent_streams:
        latest = await run_in_threadpool(
            bridge.store.get_latest_sse_event_containing,
            "agent", thread_id, "radiomics_progress",
        )
        if latest:
            try:
                parsed = json.loads(latest["data"])
            except (TypeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict) and parsed.get("radiomics_progress"):
                catch_up_data = latest["data"]

    async def event_generator():
        queue: asyncio.Queue = await bridge.subscribe(
            "agent", thread_id, last_event_id=last_event_id
        )
        try:
            if catch_up_data is not None:
                yield f"event: agent\ndata: {catch_up_data}\n\n"
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
