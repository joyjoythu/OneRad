import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage, convert_to_openai_messages
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from openai import OpenAI

from app.agent.state import AgentState
from app.agent.tools import build_tools
from app.agent.safety import Sandbox
from app.agent import runtime as agent_runtime
from app.actions import execute_plan
from app.code_runner import execute_script_if_safe
from app.feature import FeatureAgent
from app.radiomics_analysis import run_radiomics_cv_analysis
from app.constants import DEEPSEEK_MODEL
from app.skills import load_skill_bundle

logger = logging.getLogger(__name__)


def _resolve_model(state: AgentState, config: Optional[RunnableConfig] = None) -> str:
    """Return OneRad's fixed model, ignoring legacy checkpoint values."""
    return DEEPSEEK_MODEL


def _build_llm(
    api_key: str, state: AgentState, config: Optional[RunnableConfig] = None
) -> ChatOpenAI:
    """根据状态构造 ChatOpenAI 实例（供工具内部调用，如 plan_file_operations）。"""
    return ChatOpenAI(
        api_key=api_key or None,
        base_url=state["base_url"],
        model=_resolve_model(state, config),
        temperature=0.2,
    )


def _resolve_api_key(state: AgentState, config: Optional[RunnableConfig] = None) -> str:
    """优先从 RunnableConfig 读取 api_key，兼容旧测试直接传入 state。

    未在请求中显式提供时，回退到 OPENAI_API_KEY 或 DEEPSEEK_API_KEY 环境变量，
    保证 Agent 与直接分析流程在凭证获取上保持一致。
    """
    if config is not None:
        api_key = config.get("configurable", {}).get("api_key", "")
        if api_key:
            return api_key
    api_key = state.get("api_key", "")
    if api_key:
        return api_key
    return os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""


def _extract_context_usage(response: Any) -> Optional[Dict[str, int]]:
    """从 AIMessage.usage_metadata 提取 token 用量；缺失时返回 None。"""
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def call_llm(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """流式调用 LLM，边收 reasoning_content 边推送 thinking 事件，组装 AIMessage。"""
    api_key = _resolve_api_key(state, config)
    llm = _build_llm(api_key, state, config)
    tools = build_tools(state["project_path"], llm)
    thread_id = (config or {}).get("configurable", {}).get("thread_id")
    response = _stream_chat_completion(
        api_key=api_key,
        base_url=state["base_url"],
        model=_resolve_model(state, config),
        messages=[
            SystemMessage(
                content=load_skill_bundle(("agent-core", "radiomics-workflow"))
            ),
            *state["messages"],
        ],
        tools=list(tools.values()),
        thread_id=thread_id,
    )
    updates: dict = {"messages": [response]}
    usage = _extract_context_usage(response)
    if usage is not None:
        updates["context_usage"] = usage
    return updates


def _stream_chat_completion(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Any],
    tools: List[Any],
    thread_id: Optional[str] = None,
) -> AIMessage:
    """openai SDK 流式调用 DeepSeek，返回组装好的 AIMessage。

    LangChain 的 ChatOpenAI 会丢弃 DeepSeek 的非标准 reasoning_content 字段，
    因此直接用 openai SDK：流式循环中累积 reasoning/content/tool_calls 三类
    delta，reasoning 累积全文经 _publish_thinking 旁路推送给前端；思考链最终
    挂在 AIMessage.additional_kwargs["reasoning_content"] 上随快照持久化。
    """
    with OpenAI(api_key=api_key or None, base_url=base_url) as client:
        stream = client.chat.completions.create(
            model=model,
            messages=convert_to_openai_messages(messages),
            tools=[convert_to_openai_tool(t) for t in tools],
            temperature=0.2,
            parallel_tool_calls=False,
            stream=True,
            stream_options={"include_usage": True},
        )

        reasoning_parts: List[str] = []
        content_parts: List[str] = []
        tool_slots: Dict[int, Dict[str, str]] = {}
        usage_metadata = None

        _publish_thinking(thread_id, "", False)
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                usage_metadata = {
                    "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                }
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_parts.append(reasoning)
                _publish_thinking(thread_id, "".join(reasoning_parts), False)
            if getattr(delta, "content", None):
                content_parts.append(delta.content)
            for tc in getattr(delta, "tool_calls", None) or []:
                slot = tool_slots.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] += tc.id
                function = getattr(tc, "function", None)
                if function is not None:
                    if getattr(function, "name", None):
                        slot["name"] += function.name
                    if getattr(function, "arguments", None):
                        slot["arguments"] += function.arguments

        full_reasoning = "".join(reasoning_parts)
        _publish_thinking(thread_id, full_reasoning, True)

        tool_calls = []
        for index in sorted(tool_slots):
            slot = tool_slots[index]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"工具调用参数不是合法 JSON（{slot['name']}）: {slot['arguments']}"
                ) from exc
            tool_calls.append({
                "name": slot["name"],
                "args": args,
                "id": slot["id"] or f"call_{index}",
                "type": "tool_call",
            })

    additional_kwargs: Dict[str, Any] = {}
    if full_reasoning:
        additional_kwargs["reasoning_content"] = full_reasoning
    return AIMessage(
        content="".join(content_parts),
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
        usage_metadata=usage_metadata,
    )


def should_continue(state: AgentState) -> Literal["process_tool_calls", "__end__"]:
    """判断 LLM 输出是否包含工具调用。"""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "process_tool_calls"
    return "__end__"


def process_tool_calls(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """处理 LLM 输出的工具调用，设置对应的中断状态或返回 ToolMessage。"""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", [])
    if not tool_calls:
        return {"interrupt_type": None}

    api_key = _resolve_api_key(state, config)
    llm = _build_llm(api_key, state, config)
    tools = build_tools(state["project_path"], llm)

    updates = {"messages": []}
    interrupt_type = None
    # 同一轮 LLM 输出中最多只允许一个需要人工确认的工具调用，
    # 避免 pending 被覆盖导致部分 tool_call_id 缺少响应。
    confirmation_pending = False

    for tc in tool_calls:
        name = tc.get("name") if isinstance(tc, dict) else None
        args = tc.get("args") if isinstance(tc, dict) else None
        tool_call_id = tc.get("id") if isinstance(tc, dict) else ""

        if not name or not isinstance(args, dict) or name not in tools:
            error = {"error": f"Invalid or unknown tool call: {name}"}
            updates["messages"].append(ToolMessage(
                content=json.dumps(error),
                tool_call_id=tool_call_id or "",
            ))
            continue

        tool_result = tools[name].invoke(args)
        try:
            parsed = json.loads(tool_result)
        except json.JSONDecodeError:
            updates["messages"].append(ToolMessage(
                content=json.dumps({"error": f"Tool {name} returned invalid JSON"}),
                tool_call_id=tool_call_id,
            ))
            continue

        needs_confirmation = name in {
            "list_directory",
            "find_files",
            "get_file_info",
            "plan_file_operations",
            "discover_radiomics_pairs",
            "extract_radiomics_features",
            "run_radiomics_analysis",
        } or (
            name == "execute_python_script"
            and isinstance(parsed, dict)
            and "_pending_tool" in parsed
            and "script" in parsed
        )

        if needs_confirmation:
            if confirmation_pending:
                # 已经有一个需要确认的工具在处理中；为该 tool_call_id 返回错误响应，
                # 保证 assistant 的 tool_calls 后每个 id 都有 tool 消息。
                updates["messages"].append(ToolMessage(
                    content=json.dumps({
                        "error": "一次只能处理一个需要确认的操作，请重新请求",
                    }),
                    tool_call_id=tool_call_id,
                ))
                continue
            confirmation_pending = True
            if name in {"list_directory", "find_files", "get_file_info"}:
                interrupt_type = "system_command"
                updates["pending_command"] = {"tool_call_id": tool_call_id, **parsed}
            elif name == "plan_file_operations":
                interrupt_type = "file_plan"
                updates["pending_plan"] = {"tool_call_id": tool_call_id, "plan": parsed}
            elif name == "execute_python_script":
                interrupt_type = "python_script"
                updates["pending_script"] = {"tool_call_id": tool_call_id, **parsed["script"]}
                updates["script_risk_level"] = parsed["script"]["risk_level"]
            elif name == "discover_radiomics_pairs":
                if not isinstance(parsed, dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if parsed.get("success") is False and not parsed.get("_pending_tool"):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps(parsed),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                # 需要用户确认：标记为 pending 计划（防御性处理未知 dict）
                interrupt_type = "radiomics_plan"
                updates["pending_radiomics_plan"] = {"tool_call_id": tool_call_id, **parsed}
            elif name == "extract_radiomics_features":
                if not isinstance(parsed, dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if parsed.get("success") is False and not parsed.get("_pending_tool"):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps(parsed),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if not isinstance(parsed.get("meta"), dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                interrupt_type = "radiomics_execution"
                updates["pending_radiomics_execution"] = {"tool_call_id": tool_call_id, **parsed["meta"]}
            elif name == "run_radiomics_analysis":
                if not isinstance(parsed, dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if "_pending_tool" not in parsed:
                    # 识别阶段结果（need_clarification / error）直接回给 LLM，
                    # 由 LLM 在对话中向用户澄清后重新调用。
                    updates["messages"].append(ToolMessage(
                        content=tool_result,
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if not isinstance(parsed.get("meta"), dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                interrupt_type = "radiomics_analysis"
                updates["pending_radiomics_analysis"] = {"tool_call_id": tool_call_id, **parsed["meta"]}
            # 需要确认的工具不在此处生成 ToolMessage，由 execute_confirmed 在用户确认/取消后统一补齐。
        else:
            updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tool_call_id))

    updates["interrupt_type"] = interrupt_type
    return updates


def route_after_process(
    state: AgentState, config: RunnableConfig
) -> Literal["human_review", "auto_confirm", "call_llm"]:
    """根据是否有待确认的中断决定路由；自动审批开启时跳过人工确认。"""
    if not state.get("interrupt_type"):
        return "call_llm"
    if config.get("configurable", {}).get("auto_approve"):
        return "auto_confirm"
    return "human_review"


def auto_confirm(state: AgentState) -> dict:
    """自动审批：跳过 human_review，直接标记为已确认。"""
    return {"confirmed": True}


def human_review(state: AgentState) -> dict:
    """通过 interrupt 暂停并等待用户确认、编辑或取消。"""
    value = interrupt({
        "type": state["interrupt_type"],
        "plan": state.get("pending_plan"),
        "command": state.get("pending_command"),
        "script": state.get("pending_script"),
        "radiomics_plan": state.get("pending_radiomics_plan"),
        "radiomics_execution": state.get("pending_radiomics_execution"),
        "radiomics_analysis": state.get("pending_radiomics_analysis"),
    })
    if not isinstance(value, dict):
        value = {"action": "cancel"}

    pending_plan = state.get("pending_plan")
    if "plan" in value and pending_plan:
        pending_plan = {"tool_call_id": pending_plan["tool_call_id"], "plan": value["plan"]}

    pending_radiomics_plan = state.get("pending_radiomics_plan")
    if "radiomics_plan" in value and pending_radiomics_plan:
        pending_radiomics_plan = {"tool_call_id": pending_radiomics_plan["tool_call_id"], **value["radiomics_plan"]}

    return {
        "confirmed": value.get("action") == "confirm",
        "pending_plan": pending_plan,
        "pending_radiomics_plan": pending_radiomics_plan,
        "pending_radiomics_execution": state.get("pending_radiomics_execution"),
        "pending_radiomics_analysis": state.get("pending_radiomics_analysis"),
    }


def _resolve_tool_call_id(state: AgentState) -> str:
    """从中断的 pending 状态或最近一条 assistant 消息中解析 tool_call_id。"""
    for pending in (
        state.get("pending_plan"),
        state.get("pending_command"),
        state.get("pending_script"),
        state.get("pending_radiomics_plan"),
        state.get("pending_radiomics_execution"),
        state.get("pending_radiomics_analysis"),
    ):
        if pending:
            return pending.get("tool_call_id", "") or ""
    last = state["messages"][-1] if state.get("messages") else None
    tool_calls = getattr(last, "tool_calls", []) if last else []
    if tool_calls:
        return tool_calls[0].get("id", "") or ""
    return ""


def _publish_agent_progress(thread_id: Optional[str], payload: Optional[dict]) -> None:
    """从节点线程向 SSE 订阅者推送影像组学提取进度。

    节点运行在工作线程中，需通过 run_coroutine_threadsafe 回到主事件循环发布。
    上下文缺失（线程未在运行）或事件循环已关闭时静默跳过。
    """
    ctx = agent_runtime.get(thread_id)
    if ctx is None or ctx.loop is None or ctx.bridge is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            ctx.bridge.publish(
                "agent", thread_id, {"radiomics_progress": payload, "running": True}
            ),
            ctx.loop,
        )
    except Exception:
        logger.debug("推送提取进度失败", exc_info=True)


def _publish_thinking(thread_id: Optional[str], text: str, done: bool) -> None:
    """从节点线程向 SSE 订阅者推送模型思考链（reasoning_content）。

    与 _publish_agent_progress 同模式：节点在工作线程中运行，经
    run_coroutine_threadsafe 回到主事件循环发布。发送累积全文而非增量，
    丢事件/重连均自洽。persist=False 避免高频 delta 撑大 sse_events 表；
    重连后的兜底是 values 快照里 AIMessage 携带的完整思考链。
    """
    ctx = agent_runtime.get(thread_id)
    if ctx is None or ctx.loop is None or ctx.bridge is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            ctx.bridge.publish(
                "agent",
                thread_id,
                {"thinking": {"text": text, "done": done}, "running": True},
                persist=False,
            ),
            ctx.loop,
        )
    except Exception:
        logger.debug("推送思考内容失败", exc_info=True)


def execute_confirmed(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """根据用户确认结果执行待处理操作或取消，并清空中断状态。"""
    itype = state["interrupt_type"]

    thread_id = (config or {}).get("configurable", {}).get("thread_id")

    pending_plan = state.get("pending_plan")
    pending_command = state.get("pending_command")
    pending_script = state.get("pending_script")
    pending_radiomics_plan = state.get("pending_radiomics_plan")
    pending_radiomics_execution = state.get("pending_radiomics_execution")
    pending_radiomics_analysis = state.get("pending_radiomics_analysis")

    if itype == "file_plan":
        tool_call_id = (pending_plan or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_plan:
            if not tool_call_id:
                raise RuntimeError("Missing pending plan and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending plan"}),
                    tool_call_id=tool_call_id,
                )]
            })
    elif itype == "system_command":
        tool_call_id = (pending_command or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_command:
            if not tool_call_id:
                raise RuntimeError("Missing pending command and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending command"}),
                    tool_call_id=tool_call_id,
                )]
            })
    elif itype == "python_script":
        tool_call_id = (pending_script or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_script:
            if not tool_call_id:
                raise RuntimeError("Missing pending script and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending script"}),
                    tool_call_id=tool_call_id,
                )]
            })
    elif itype == "radiomics_plan":
        tool_call_id = (pending_radiomics_plan or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_radiomics_plan:
            if not tool_call_id:
                raise RuntimeError("Missing pending radiomics plan and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending radiomics plan"}),
                    tool_call_id=tool_call_id,
                )]
            })
    elif itype == "radiomics_execution":
        tool_call_id = (pending_radiomics_execution or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_radiomics_execution:
            if not tool_call_id:
                raise RuntimeError("Missing pending radiomics execution and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending radiomics execution"}),
                    tool_call_id=tool_call_id,
                )]
            })
    elif itype == "radiomics_analysis":
        tool_call_id = (pending_radiomics_analysis or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_radiomics_analysis:
            if not tool_call_id:
                raise RuntimeError("Missing pending radiomics analysis and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending radiomics analysis"}),
                    tool_call_id=tool_call_id,
                )]
            })
    else:
        tool_call_id = _resolve_tool_call_id(state)
        if not tool_call_id:
            raise RuntimeError(f"Unknown interrupt type {itype} and cannot resolve tool_call_id")
        content = json.dumps({"error": f"unknown interrupt type: {itype}"})
        return _clear_interrupt({
            "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]
        })

    if not state.get("confirmed"):
        content = json.dumps({"cancelled": True, "reason": "用户取消了操作"})
        return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    if itype == "file_plan":
        results = execute_plan(state["pending_plan"]["plan"], state["project_path"])
    elif itype == "system_command":
        results = _run_system_command(state["pending_command"], state["project_path"])
    elif itype == "python_script":
        results = execute_script_if_safe(state["pending_script"], state["project_path"])
    elif itype == "radiomics_plan":
        plan = state["pending_radiomics_plan"]
        results = {k: v for k, v in plan.items() if k != "tool_call_id"}
    elif itype == "radiomics_execution":
        ctx = agent_runtime.get(thread_id)
        cancel_event = ctx.cancel_event if ctx is not None else None

        def progress_callback(payload: dict) -> None:
            _publish_agent_progress(thread_id, payload)

        try:
            results = _run_radiomics_execution(
                state["pending_radiomics_execution"],
                state["project_path"],
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )
        finally:
            # 节点结束后清除前端进度显示（后续 call_llm 阶段不再属于提取）。
            _publish_agent_progress(thread_id, None)
    elif itype == "radiomics_analysis":
        ctx = agent_runtime.get(thread_id)
        cancel_event = ctx.cancel_event if ctx is not None else None
        results = _run_radiomics_analysis(
            state["pending_radiomics_analysis"],
            state["project_path"],
            cancel_event=cancel_event,
        )
    else:
        results = {"error": "unknown interrupt type"}

    content = json.dumps(results)
    return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})


def _run_system_command(command: dict, project_path: str) -> dict:
    """执行已确认的系统命令。"""
    tool = command.get("_pending_tool") or command.get("tool")
    args = command.get("args", {})
    sandbox = Sandbox(project_path)
    try:
        if tool == "list_directory":
            path = args.get("path")
            if path is None:
                return {"error": "missing required argument: path"}
            target = sandbox.resolve(path)
            entries = [f"{'D' if e.is_dir() else 'F'} {e.name}" for e in sorted(target.iterdir())]
            return {"tool": tool, "result": "\n".join(entries)}
        elif tool == "find_files":
            target = sandbox.resolve(args.get("path", "."))
            pattern = args.get("pattern")
            if pattern is None:
                return {"error": "missing required argument: pattern"}
            matches = list(target.rglob(pattern))[:100]
            return {"tool": tool, "result": [str(m.relative_to(sandbox.root)) for m in matches]}
        elif tool == "get_file_info":
            path = args.get("path")
            if path is None:
                return {"error": "missing required argument: path"}
            target = sandbox.resolve(path, must_exist=True)
            st = target.stat()
            return {
                "tool": tool,
                "result": {
                    "path": str(target.relative_to(sandbox.root)),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "is_dir": target.is_dir(),
                },
            }
        return {"error": f"unknown command {tool}"}
    except Exception as e:
        return {"error": str(e)}


class PathEscapeError(ValueError):
    """Raised when a requested path resolves outside the project sandbox."""


def _resolve_within_project(sandbox: Sandbox, path) -> str:
    """Resolve *path* inside *sandbox* and re-raise sandbox escapes as PathEscapeError.

    This lets callers distinguish path-escape failures from unrelated ValueErrors
    raised by downstream code (e.g. FeatureAgent.run).
    """
    try:
        return str(sandbox.resolve(path, must_exist=False))
    except ValueError as e:
        msg = str(e).lower()
        if "outside project sandbox" in msg or "sandbox" in msg:
            raise PathEscapeError(str(e)) from e
        raise


def _run_radiomics_execution(
    pending: dict,
    project_path: str,
    progress_callback=None,
    cancel_event=None,
) -> dict:
    """执行已确认的影像组学特征提取任务。"""
    sandbox = Sandbox(project_path)
    yaml_path = pending.get("yaml_path") or str(Path(project_path) / "Params_labels.yaml")
    output_dir = pending.get("output_dir") or str(Path(project_path) / "radiomics_features")
    pairs = pending.get("pairs", [])
    try:
        yaml_path = _resolve_within_project(sandbox, yaml_path)
        output_dir = _resolve_within_project(sandbox, output_dir)
        resolved_pairs = []
        for pair in pairs:
            resolved = dict(pair)
            resolved["image_path"] = _resolve_within_project(
                sandbox, pair.get("image_path")
            )
            resolved["mask_path"] = _resolve_within_project(
                sandbox, pair.get("mask_path")
            )
            resolved_pairs.append(resolved)
        agent = FeatureAgent(output_dir=output_dir)
        result = agent.run(
            resolved_pairs,
            yaml_path=yaml_path,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
        return _json_safe_radiomics_result(result)
    except PathEscapeError:
        return {"success": False, "error": "路径超出项目目录"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ToolMessage 内容必须可 JSON 序列化。FeatureAgent.run 的返回中含有
# feature_df（pandas DataFrame），直接 json.dumps 会让 execute_confirmed 节点
# 在提取完成后崩溃，interrupt_type 无法清除，线程卡死在待确认状态。
_RADIOMICS_SUMMARY_KEYS = (
    "success",
    "cancelled",
    "message",
    "feature_path",
    "failed_path",
    "h5_dir",
    "n_samples",
    "n_success",
    "n_failed",
    "failed_ids",
    "failed_examples",
    "zero_variance_features",
    "settings_used",
    "extraction_time_seconds",
)
_MAX_FEATURE_NAMES_IN_SUMMARY = 50


def _run_radiomics_analysis(
    pending: dict,
    project_path: str,
    cancel_event=None,
) -> dict:
    """执行已确认的影像组学分析任务。"""
    sandbox = Sandbox(project_path)
    try:
        feature_csv = _resolve_within_project(sandbox, pending.get("feature_csv"))
        clinical = _resolve_within_project(sandbox, pending.get("clinical"))
        output_dir = _resolve_within_project(
            sandbox,
            pending.get("output_dir") or str(Path(project_path) / "radiomics_analysis"),
        )
        should_cancel = (lambda: cancel_event.is_set()) if cancel_event is not None else None
        result = run_radiomics_cv_analysis(
            feature_csv=feature_csv,
            clinical=clinical,
            output_dir=output_dir,
            id_col=pending.get("id_col"),
            label_col=pending.get("label_col"),
            covariates=pending.get("covariates") or [],
            should_cancel=should_cancel,
        )
        return _json_safe_analysis_result(result)
    except PathEscapeError:
        return {"success": False, "error": "路径超出项目目录"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _json_safe_analysis_result(result: dict) -> dict:
    """分析结果转 JSON 安全摘要：指标/特征/产物路径，剔除 oof 大数组。"""
    analysis = result.get("analysis_result") or {}
    payload = {
        "success": result.get("success", False),
        "cancelled": result.get("cancelled", False),
        "message": result.get("message", ""),
        "n_samples": analysis.get("n_samples"),
        "n_matched": result.get("n_matched"),
        "selected_features": analysis.get("selected_features", []),
        "metrics": analysis.get("metrics", {}),
        "outputs": result.get("outputs", {}),
    }
    if not payload["success"] and not payload["message"]:
        payload["message"] = result.get("error", "")
    if not payload["success"]:
        payload["error"] = payload["message"]
    return payload


def _json_safe_radiomics_result(result: dict) -> dict:
    """提取结果转为 JSON 安全摘要：剔除 DataFrame，特征名列表截断。"""
    summary = {k: result[k] for k in _RADIOMICS_SUMMARY_KEYS if k in result}
    feature_names = result.get("feature_names") or []
    summary["n_features"] = len(feature_names)
    summary["feature_names"] = feature_names[:_MAX_FEATURE_NAMES_IN_SUMMARY]
    if len(feature_names) > _MAX_FEATURE_NAMES_IN_SUMMARY:
        summary["feature_names_truncated"] = True
    return summary


def _clear_interrupt(updates: dict) -> dict:
    """清空中断相关状态字段。"""
    updates.update({
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "pending_radiomics_plan": None,
        "pending_radiomics_execution": None,
        "pending_radiomics_analysis": None,
        "script_risk_level": None,
        "confirmed": None,
    })
    return updates
