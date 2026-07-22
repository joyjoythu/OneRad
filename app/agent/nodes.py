import asyncio
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from langgraph.errors import GraphRecursionError
from openai import OpenAI

from app.agent.state import AgentState
from app.agent.tools import build_tools
from app.agent.safety import Sandbox
from app.agent import runtime as agent_runtime
from app.actions import execute_plan
from app.code_runner import execute_script_if_safe
from app.feature import FeatureAgent
from app.radiomics_analysis import run_radiomics_cv_analysis
from app.constants import DEEPSEEK_MODEL, DEEPSEEK_MODELS
from app.skills import load_skill_bundle

logger = logging.getLogger(__name__)


def _resolve_model(state: AgentState, config: Optional[RunnableConfig] = None) -> str:
    """返回该会话选定的模型；旧检查点里不受支持的模型名回退到默认模型。"""
    model = state.get("model")
    return model if model in DEEPSEEK_MODELS else DEEPSEEK_MODEL


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


def _allow_subagent(config: Optional[RunnableConfig] = None) -> bool:
    """是否允许使用 dispatch_subagent 工具。主线程默认允许；
    子 agent 运行时显式置 False，限制嵌套深度为 1。"""
    if config is None:
        return True
    return bool(config.get("configurable", {}).get("allow_subagent", True))


def _readonly_tools(config: Optional[RunnableConfig] = None) -> bool:
    """是否只挂载只读探索工具（list/find/info/read_yaml/read_json/read_tabular_file/discover_pairs/inspect_image_spacing）。
    explore 模式的子 agent 置 True，使其免确认也无法写文件或跑脚本。"""
    if config is None:
        return False
    return bool(config.get("configurable", {}).get("readonly_tools", False))


def call_llm(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """流式调用 LLM，边收 reasoning_content 边推送 thinking 事件，组装 AIMessage。"""
    api_key = _resolve_api_key(state, config)
    llm = _build_llm(api_key, state, config)
    tools = build_tools(
        state["project_path"],
        llm,
        allow_subagent=_allow_subagent(config),
        readonly=_readonly_tools(config),
    )
    thread_id = (config or {}).get("configurable", {}).get("thread_id")
    response = _stream_chat_completion(
        api_key=api_key,
        base_url=state["base_url"],
        model=_resolve_model(state, config),
        messages=[
            SystemMessage(
                content=load_skill_bundle(
                    ("agent-core", "radiomics-workflow", "word-report"))
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
    tools = build_tools(
        state["project_path"],
        llm,
        allow_subagent=_allow_subagent(config),
        readonly=_readonly_tools(config),
    )

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

        try:
            tool_result = tools[name].invoke(args)
        except Exception as exc:
            # 参数校验或工具自身执行失败不应中断整张图：回复错误 ToolMessage，
            # 保证 assistant 的 tool_calls 后每个 id 都有 tool 消息（否则历史
            # 残缺，之后每轮 LLM 调用都会 400），模型看到错误后可换参数重试。
            updates["messages"].append(ToolMessage(
                content=json.dumps(
                    {"error": f"Tool {name} 调用失败: {exc}"},
                    ensure_ascii=False,
                ),
                tool_call_id=tool_call_id or "",
            ))
            continue
        try:
            parsed = json.loads(tool_result)
        except json.JSONDecodeError:
            updates["messages"].append(ToolMessage(
                content=json.dumps({"error": f"Tool {name} returned invalid JSON"}),
                tool_call_id=tool_call_id,
            ))
            continue

        # 计划面板更新：免确认，直接写入 state.todos，随 SSE 同步到前端。
        if name == "update_todo_list" and isinstance(parsed, dict):
            if parsed.get("success"):
                todos = parsed["todos"]
                updates["todos"] = todos
                done = sum(1 for t in todos if t.get("status") == "completed")
                updates["operation_log"] = [{
                    "time": datetime.now(timezone.utc).isoformat(),
                    "text": f"计划面板已更新（{done}/{len(todos)} 已完成）",
                }]
            updates["messages"].append(ToolMessage(
                content=json.dumps(parsed, ensure_ascii=False),
                tool_call_id=tool_call_id,
            ))
            continue

        # 只读探索模式的子 agent 派发：免确认，不占 confirmation 名额，
        # 直接在本节点内并行执行并把汇总结果作为 ToolMessage 返回。
        if (
            name == "dispatch_subagent"
            and isinstance(parsed, dict)
            and parsed.get("mode") == "explore"
            and parsed.get("tasks")
        ):
            thread_id = (config or {}).get("configurable", {}).get("thread_id")
            results = _run_subagents(
                {"tasks": parsed["tasks"], "mode": "explore"},
                state,
                config,
                thread_id,
            )
            updates["messages"].append(ToolMessage(
                content=json.dumps(results, ensure_ascii=False),
                tool_call_id=tool_call_id,
            ))
            continue

        # 结果解读：免确认，立即在本节点内执行（一次 LLM 调用 + 幂等重写报告），
        # 与分析成功后的自动补全流程衔接，不再额外打断用户。
        if name == "interpret_analysis_results":
            results = _run_interpretation(state, config)
            updates["messages"].append(ToolMessage(
                content=json.dumps(results, ensure_ascii=False),
                tool_call_id=tool_call_id,
            ))
            continue

        # 报告重排：免确认，幂等且自动保留 .bak 备份，直接在本节点内执行。
        if name == "reformat_report":
            results = _run_reformat_report(state)
            updates["messages"].append(ToolMessage(
                content=json.dumps(results, ensure_ascii=False),
                tool_call_id=tool_call_id,
            ))
            continue

        needs_confirmation = name in {
            "list_directory",
            "find_files",
            "get_file_info",
            "read_yaml",
            "read_json",
            "read_tabular_file",
            "update_yaml",
            "create_json",
            "update_json",
            "plan_file_operations",
            "discover_radiomics_pairs",
            "inspect_image_spacing",
            "extract_radiomics_features",
            "run_radiomics_analysis",
            "run_feature_statistics",
            "dispatch_subagent",
            "ask_user_choice",
            "word_create",
            "word_append",
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
            if name in {"list_directory", "find_files", "get_file_info",
                        "read_yaml", "read_json", "read_tabular_file", "update_yaml",
                        "create_json", "update_json",
                        "inspect_image_spacing",
                        "word_create", "word_append"}:
                interrupt_type = "system_command"
                updates["pending_command"] = {"tool_call_id": tool_call_id, **parsed}
            elif name == "dispatch_subagent":
                if not isinstance(parsed, dict) or not parsed.get("tasks"):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                interrupt_type = "subagent_dispatch"
                updates["pending_subagent"] = {
                    "tool_call_id": tool_call_id,
                    "tasks": parsed["tasks"],
                }
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
            elif name == "run_feature_statistics":
                if not isinstance(parsed, dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if "_pending_tool" not in parsed:
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
                interrupt_type = "feature_statistics"
                updates["pending_feature_statistics"] = {"tool_call_id": tool_call_id, **parsed["meta"]}
            elif name == "ask_user_choice":
                if not isinstance(parsed, dict) or not parsed.get("question"):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                interrupt_type = "user_choice"
                updates["pending_choice"] = {
                    "tool_call_id": tool_call_id,
                    "question": parsed["question"],
                    "options": parsed["options"],
                }
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
    # 提问必须等待真实用户回答，自动审批不能代答（否则答案为空）。
    if state["interrupt_type"] == "user_choice":
        return "human_review"
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
        "feature_statistics": state.get("pending_feature_statistics"),
        "subagent": state.get("pending_subagent"),
        "choice": state.get("pending_choice"),
    })
    if not isinstance(value, dict):
        value = {"action": "cancel"}

    pending_plan = state.get("pending_plan")
    if "plan" in value and pending_plan:
        pending_plan = {"tool_call_id": pending_plan["tool_call_id"], "plan": value["plan"]}

    pending_radiomics_plan = state.get("pending_radiomics_plan")
    if "radiomics_plan" in value and pending_radiomics_plan:
        pending_radiomics_plan = {"tool_call_id": pending_radiomics_plan["tool_call_id"], **value["radiomics_plan"]}

    action = value.get("action")
    return {
        # "answer"（选择面板提交）与 "confirm" 一样进入执行分支：
        # execute_confirmed 的 user_choice 分支把答案作为工具结果返回。
        "confirmed": action in ("confirm", "answer"),
        "other_instruction": value.get("instruction") if action == "other" else None,
        "choice_answer": value.get("answer") if action == "answer" else None,
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
        state.get("pending_feature_statistics"),
        state.get("pending_subagent"),
        state.get("pending_choice"),
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
    # /stop 置位取消事件后不再推送进度：流式任务已被取消，继续推送
    # running:True 会把前端 busy 重新置回运行中，看起来"后台还在跑"。
    if ctx.cancel_event.is_set():
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
    elif itype == "feature_statistics":
        pending_feature_statistics = state.get("pending_feature_statistics")
        tool_call_id = (pending_feature_statistics or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_feature_statistics:
            if not tool_call_id:
                raise RuntimeError("Missing pending feature statistics and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending feature statistics"}),
                    tool_call_id=tool_call_id,
                )]
            })
    elif itype == "subagent_dispatch":
        pending_subagent = state.get("pending_subagent")
        tool_call_id = (pending_subagent or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_subagent:
            if not tool_call_id:
                raise RuntimeError("Missing pending subagent and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending subagent"}),
                    tool_call_id=tool_call_id,
                )]
            })
    elif itype == "user_choice":
        pending_choice = state.get("pending_choice")
        tool_call_id = (pending_choice or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_choice:
            if not tool_call_id:
                raise RuntimeError("Missing pending choice and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending choice"}),
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
        instruction = state.get("other_instruction")
        reason = "用户取消了操作并提供了替代指令" if instruction else "用户取消了操作"
        content = json.dumps({"cancelled": True, "reason": reason})
        messages: list = [ToolMessage(content=content, tool_call_id=tool_call_id)]
        if instruction:
            messages.append(HumanMessage(content=instruction))
        else:
            # 用户直接取消（未提供替代指令）时，追加一条 HumanMessage
            # 明确告知 LLM 用户希望停止当前操作。
            # 仅对耗时/多阶段操作（影像组学提取、分析、文件计划）追加，
            # 避免对简单查询（list_directory 等）产生多余对话轮次。
            if itype in (
                "radiomics_plan",
                "radiomics_execution",
                "radiomics_analysis",
                "feature_statistics",
                "file_plan",
                "python_script",
                "subagent_dispatch",
            ):
                messages.append(HumanMessage(
                    content="我取消了刚才的操作，请不要重试。请询问我现在想做什么。"
                ))
        return _clear_interrupt({"messages": messages})

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
        if ctx is None:
            # 运行时上下文缺失时的兜底：注册一个临时上下文，保证
            # cancel_event 不为 None，/stop 也能找到并置位。
            logger.warning(
                "execute_confirmed: thread_id=%s 缺少运行时上下文，注册临时兜底",
                thread_id,
            )
            ctx = agent_runtime.register(thread_id)
        cancel_event = ctx.cancel_event

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
        if ctx is None:
            logger.warning(
                "execute_confirmed: thread_id=%s 缺少运行时上下文，注册临时兜底",
                thread_id,
            )
            ctx = agent_runtime.register(thread_id)
        cancel_event = ctx.cancel_event
        results = _run_radiomics_analysis(
            state["pending_radiomics_analysis"],
            state["project_path"],
            cancel_event=cancel_event,
        )
    elif itype == "feature_statistics":
        results = _run_feature_statistics(
            state["pending_feature_statistics"],
            state["project_path"],
        )
    elif itype == "subagent_dispatch":
        results = _run_subagents(state["pending_subagent"], state, config, thread_id)
    elif itype == "user_choice":
        results = {"answer": state.get("choice_answer") or ""}
    else:
        results = {"error": "unknown interrupt type"}

    # 显式标记"已执行"：各工具文档普遍写着"执行前需要用户确认"，裸执行
    # 结果会让 LLM 误读为"计划已生成"而再次要求确认（真实案例：rename 已
    # 执行完成，agent 却回复"需要您确认执行…确认执行吗？"）。
    # dict 结果采用键注入而非整体包裹，保持原有字段在顶层可读。
    note = "用户已确认，操作已执行完成。请直接向用户总结执行结果，不要再要求确认。"
    if isinstance(results, dict):
        results = {"executed": True, "note": note, **results}
    else:
        results = {"executed": True, "note": note, "results": results}
    content = json.dumps(results, ensure_ascii=False)
    return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})


SUBAGENT_SYSTEM_PROMPT = (
    "你是被主 agent 分派的子任务 agent，在项目目录内独立完成用户交给你的任务。"
    "你可以使用全部工具（文件探查、Python 脚本、影像组学等），工具调用会自动批准执行，"
    "无需等待用户确认；用户也看不到你的中间过程，因此不要向用户提问。"
    "完成后用简洁的中文输出最终结论：做了什么、关键结果、产出文件的相对路径。"
)

EXPLORE_SUBAGENT_SYSTEM_PROMPT = (
    "你是被主 agent 分派的只读探索子 agent，在项目目录内独立完成交给你的探索任务。"
    "你只能使用只读工具（目录列举、文件搜索、文件元信息、影像组学配对扫描、影像 spacing 检测），"
    "无法运行脚本或修改任何文件；工具调用会自动批准执行，无需等待用户确认，"
    "用户也看不到你的中间过程，因此不要向用户提问。"
    "完成后用简洁的中文汇报发现：目录结构、关键数据文件、配对情况、可疑问题或缺失项。"
)

# 子 agent 结论带回主对话的长度上限（隔离上下文的初衷：中间过程不进主对话）。
_SUBAGENT_RESULT_MAX_CHARS = 4000
# 推送给前端的中间过程滚动窗口（最近若干条消息摘要）。
_SUBAGENT_ENTRY_WINDOW = 8
# 子 agent 的步数上限：其整个生命周期在单次 stream 调用内完成，而每个工具
# 轮次要消耗 4 个 superstep（call_llm→process_tool_calls→auto_confirm→
# execute_confirmed），150 约等于 37 轮工具调用。主 agent 每次 resume 都是
# 新的运行（步数预算独立），子 agent 没有这种天然分段，必须显式放宽。
_SUBAGENT_RECURSION_LIMIT = 150
# 并行子任务的最大并发数：约束 LLM API 并发与本地资源占用。
_SUBAGENT_MAX_WORKERS = 4


def _run_subagents(
    pending: dict,
    state: AgentState,
    config: Optional[RunnableConfig],
    parent_thread_id: Optional[str],
) -> dict:
    """并行运行一批子任务并汇总结果。

    每个子任务由 _run_subagent 在独立线程中运行（各自的图、MemorySaver、
    运行时上下文互不共享，线程安全）；单任务时直接在当前线程内联执行。
    """
    tasks = pending.get("tasks") or []
    if not tasks:
        return {"success": False, "error": "Missing subagent tasks"}
    mode = pending.get("mode", "general")

    if len(tasks) == 1:
        results = [_run_subagent(tasks[0], state, config, parent_thread_id, mode=mode)]
    else:
        workers = min(len(tasks), _SUBAGENT_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_run_subagent, task, state, config, parent_thread_id, mode=mode)
                for task in tasks
            ]
            results = [f.result() for f in futures]

    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for r in results:
        for key in usage:
            usage[key] += (r.get("usage") or {}).get(key, 0)
    return {
        "success": all(r.get("success") for r in results),
        "results": [{"task": task, **r} for task, r in zip(tasks, results)],
        "usage": usage,
    }


def _publish_subagent(thread_id: Optional[str], payload: Dict[str, Any], persist: bool = True) -> None:
    """向父线程的 SSE 订阅者推送子 agent 运行状态。

    与 _publish_thinking 同模式：节点在工作线程中运行，经 run_coroutine_threadsafe
    回到主事件循环发布。运行中的滚动条目不持久化（persist=False），
    开始/结束状态持久化以便重连后恢复显示。
    """
    ctx = agent_runtime.get(thread_id)
    if ctx is None or ctx.loop is None or ctx.bridge is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            ctx.bridge.publish(
                "agent", thread_id, {"subagent": payload, "running": True}, persist=persist
            ),
            ctx.loop,
        )
    except Exception:
        logger.debug("推送子 agent 状态失败", exc_info=True)


def _summarize_subagent_entries(messages: List[Any]) -> List[Dict[str, str]]:
    """把子 agent 的最近若干条消息压缩成前端可展示的条目列表。"""
    entries: List[Dict[str, str]] = []
    for msg in messages[-_SUBAGENT_ENTRY_WINDOW:]:
        if isinstance(msg, AIMessage):
            names = [
                tc.get("name")
                for tc in (msg.tool_calls or [])
                if isinstance(tc, dict) and tc.get("name")
            ]
            if names:
                entries.append({"role": "assistant", "text": f"调用工具：{', '.join(names)}"})
            if isinstance(msg.content, str) and msg.content.strip():
                entries.append({"role": "assistant", "text": msg.content.strip()[:300]})
        elif isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            entries.append({"role": "tool", "text": content[:200]})
    return entries


def _extract_subagent_result(messages: List[Any]) -> tuple:
    """从子 agent 的最终消息中提取结论文本与累计 token 用量。"""
    conclusion = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            conclusion = msg.content.strip()
            break
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for msg in messages:
        meta = getattr(msg, "usage_metadata", None)
        if meta:
            usage["input_tokens"] += meta.get("input_tokens", 0)
            usage["output_tokens"] += meta.get("output_tokens", 0)
            usage["total_tokens"] += meta.get("total_tokens", 0)
    return conclusion, usage


def _run_subagent(
    task: str,
    state: AgentState,
    config: Optional[RunnableConfig],
    parent_thread_id: Optional[str],
    mode: str = "general",
) -> dict:
    """在隔离上下文中运行单个子 agent（嵌套深度限制为 1 层）。

    子 agent 使用新编译的同构图 + 独立 MemorySaver，thread_id 派生自父线程；
    auto_approve 使其内部工具自动批准（Python 脚本的 risk 分类不变，high 仍拒绝），
    工具集中不含 dispatch_subagent。mode="explore" 时进一步限制为只读探索工具集
    （readonly_tools）并换用探索专用 system prompt。中间过程经 _publish_subagent
    滚动推送到父线程的 SSE 流，只有最终结论作为工具结果回到主对话上下文。
    """
    sub_thread_id = f"{parent_thread_id or 'thread'}:sub:{uuid.uuid4().hex[:8]}"

    parent_ctx = agent_runtime.get(parent_thread_id)
    # 注册子线程上下文并共享父线程的取消事件，使 /stop 能传播到子任务；
    # 不带 loop/bridge：子线程内部的 thinking/progress 旁路推送因此静默关闭，
    # 对前端的推送统一走 _publish_subagent。
    sub_ctx = agent_runtime.register(sub_thread_id)
    if parent_ctx is not None:
        sub_ctx.cancel_event = parent_ctx.cancel_event

    status: Dict[str, Any] = {
        "id": sub_thread_id,
        "task": task,
        "status": "running",
        "entries": [],
    }
    _publish_subagent(parent_thread_id, status)

    try:
        # 延迟导入避免循环依赖（graph.py 依赖本模块的节点函数）。
        from app.agent.graph import create_agent_graph

        sub_graph = create_agent_graph()  # 默认独立 MemorySaver
        cfg = (config or {}).get("configurable", {})
        sub_config = {
            "configurable": {
                "thread_id": sub_thread_id,
                "auto_approve": True,
                "allow_subagent": False,
                "readonly_tools": mode == "explore",
                "api_key": cfg.get("api_key", ""),
                "llm_model": cfg.get("llm_model") or state["model"],
            },
            "recursion_limit": _SUBAGENT_RECURSION_LIMIT,
        }
        system_prompt = (
            EXPLORE_SUBAGENT_SYSTEM_PROMPT if mode == "explore" else SUBAGENT_SYSTEM_PROMPT
        )
        sub_input = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=task),
            ],
            "project_path": state["project_path"],
            "base_url": state["base_url"],
            "model": state["model"],
            "api_key": state.get("api_key"),
        }

        cancelled = False
        recursion_limited = False
        final: Dict[str, Any] = {}
        try:
            for values in sub_graph.stream(sub_input, sub_config, stream_mode="values"):
                final = values
                status["entries"] = _summarize_subagent_entries(values.get("messages") or [])
                _publish_subagent(parent_thread_id, status, persist=False)
                if sub_ctx.cancel_event.is_set():
                    cancelled = True
                    break
        except GraphRecursionError:
            # 步数触顶不视为失败：子 agent 已完成的探索仍有价值，
            # 下面的部分结论路径照常提取结论与用量。
            recursion_limited = True

        if cancelled:
            status["status"] = "cancelled"
            _publish_subagent(parent_thread_id, status)
            return {"success": False, "cancelled": True, "error": "子任务已被用户停止"}

        conclusion, usage = _extract_subagent_result(final.get("messages") or [])

        if recursion_limited:
            status["status"] = "done"
            _publish_subagent(parent_thread_id, status)
            return {
                "success": bool(conclusion),
                "partial": True,
                "note": (
                    f"子任务达到步数上限（{_SUBAGENT_RECURSION_LIMIT} 个 superstep，"
                    f"约 {_SUBAGENT_RECURSION_LIMIT // 4} 轮工具调用），结论基于已完成的探索"
                ),
                "result": conclusion[:_SUBAGENT_RESULT_MAX_CHARS] or "（子任务在产出结论前达到步数上限）",
                "usage": usage,
            }

        status["status"] = "done"
        _publish_subagent(parent_thread_id, status)
        return {
            "success": True,
            "result": conclusion[:_SUBAGENT_RESULT_MAX_CHARS],
            "usage": usage,
        }
    except Exception as exc:
        logger.exception("子 agent 运行失败")
        status["status"] = "failed"
        _publish_subagent(parent_thread_id, status)
        return {"success": False, "error": str(exc)}
    finally:
        agent_runtime.unregister(sub_thread_id)


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
        elif tool == "read_yaml":
            path = args.get("path")
            if path is None:
                return {"error": "missing required argument: path"}
            target = sandbox.resolve(path, must_exist=True)
            import yaml
            with open(target, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            key = args.get("key") or ""
            if key:
                for part in key.split("."):
                    if isinstance(data, dict) and part in data:
                        data = data[part]
                    else:
                        return {"error": f"键不存在: {key}（在 '{part}' 处中断）"}
            return {"tool": tool, "result": data}
        elif tool == "read_tabular_file":
            path = args.get("path")
            if path is None:
                return {"error": "missing required argument: path"}
            target = sandbox.resolve(path, must_exist=True)
            import pandas as pd
            suffix = target.suffix.lower()
            if suffix == ".csv":
                try:
                    df = pd.read_csv(target, encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(target, encoding="gbk")
            elif suffix in {".xlsx", ".xls"}:
                sheet = args.get("sheet_name") or 0
                df = pd.read_excel(target, sheet_name=sheet)
            else:
                return {"error": f"不支持的文件类型: {suffix or target.name}"
                                 f"（仅支持 .csv/.xlsx/.xls）"}
            columns_arg = args.get("columns")
            if columns_arg:
                missing = [c for c in columns_arg if c not in df.columns]
                if missing:
                    return {"error": f"列不存在: {missing}，"
                                     f"可用列: {[str(c) for c in df.columns][:50]}"}
                df = df[list(columns_arg)]
            try:
                head = int(args.get("head") if args.get("head") is not None else 20)
            except (TypeError, ValueError):
                head = 20
            head = max(0, min(head, 100))
            # to_json 自动把 NaN 转 null、numpy 类型转原生类型，保证结果可 JSON 序列化
            head_rows = json.loads(df.head(head).to_json(
                orient="records", force_ascii=False, date_format="iso"))
            columns_meta = [{"name": str(c), "dtype": str(df[c].dtype)}
                            for c in df.columns]
            result = {
                "path": str(target.relative_to(sandbox.root)),
                "shape": [int(df.shape[0]), int(df.shape[1])],
                "columns": columns_meta[:200],
                "columns_truncated": len(columns_meta) > 200,
                "head": head,
                "truncated": bool(df.shape[0] > head),
                "head_rows": head_rows,
            }
            # 宽表（如上千列的特征 CSV）预览可能超长：逐步减半行数，守住上下文体积
            while head_rows and len(json.dumps(
                    result, ensure_ascii=False)) > 12000:
                head_rows = head_rows[: len(head_rows) // 2]
                result["head_rows"] = head_rows
                result["truncated"] = True
            return {"tool": tool, "result": result}
        elif tool == "update_yaml":
            path = args.get("path")
            updates = args.get("updates")
            if path is None:
                return {"error": "missing required argument: path"}
            if not isinstance(updates, dict) or not updates:
                return {"error": "updates 必须是非空的 {点号路径: 值} 映射"}
            target = sandbox.resolve(path, must_exist=True)
            from ruamel.yaml import YAML
            rt_yaml = YAML()  # round-trip：保留注释与格式
            with open(target, "r", encoding="utf-8") as f:
                data = rt_yaml.load(f)
            if data is None:
                data = {}
            applied = []
            for dotted, value in updates.items():
                parts = str(dotted).split(".")
                node = data
                for part in parts[:-1]:
                    nxt = node.get(part) if isinstance(node, dict) else None
                    if nxt is None:
                        nxt = {}
                        node[part] = nxt
                    if not isinstance(nxt, dict):
                        return {"error": f"路径 '{dotted}' 经过非映射节点: '{part}'"}
                    node = nxt
                node[parts[-1]] = value
                applied.append(str(dotted))
            with open(target, "w", encoding="utf-8") as f:
                rt_yaml.dump(data, f)
            return {
                "tool": tool,
                "result": {
                    "path": str(target.relative_to(sandbox.root)),
                    "updated": applied,
                },
            }
        elif tool == "read_json":
            path = args.get("path")
            if path is None:
                return {"error": "missing required argument: path"}
            target = sandbox.resolve(path, must_exist=True)
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                return {"error": f"JSON 解析失败: {e}"}
            key = args.get("key") or ""
            if key:
                for part in key.split("."):
                    if isinstance(data, dict) and part in data:
                        data = data[part]
                    else:
                        return {"error": f"键不存在: {key}（在 '{part}' 处中断）"}
            return {"tool": tool, "result": data}
        elif tool == "create_json":
            path = args.get("path")
            if path is None:
                return {"error": "missing required argument: path"}
            content = args.get("content")
            if not isinstance(content, (dict, list)):
                return {"error": "content 必须是 JSON 对象（dict）或数组（list）"}
            target = sandbox.resolve(path)
            if target.exists():
                return {"error": f"文件已存在: {target.relative_to(sandbox.root)}"}
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
                f.write("\n")
            return {"tool": tool,
                    "result": {"path": str(target.relative_to(sandbox.root))}}
        elif tool == "update_json":
            path = args.get("path")
            updates = args.get("updates")
            if path is None:
                return {"error": "missing required argument: path"}
            if not isinstance(updates, dict) or not updates:
                return {"error": "updates 必须是非空的 {点号路径: 值} 映射"}
            target = sandbox.resolve(path, must_exist=True)
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                return {"error": f"JSON 解析失败: {e}"}
            if not isinstance(data, dict):
                return {"error": "顶层不是 JSON 对象，无法按点号路径更新"}
            applied = []
            deleted = []
            for dotted, value in updates.items():
                parts = str(dotted).split(".")
                node = data
                for part in parts[:-1]:
                    nxt = node.get(part) if isinstance(node, dict) else None
                    if nxt is None:
                        nxt = {}
                        node[part] = nxt
                    if not isinstance(nxt, dict):
                        return {"error": f"路径 '{dotted}' 经过非映射节点: '{part}'"}
                    node = nxt
                if value is None:
                    node.pop(parts[-1], None)
                    deleted.append(str(dotted))
                else:
                    node[parts[-1]] = value
                    applied.append(str(dotted))
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            return {
                "tool": tool,
                "result": {
                    "path": str(target.relative_to(sandbox.root)),
                    "updated": applied,
                    "deleted": deleted,
                },
            }
        elif tool == "word_create":
            filename = args.get("filename")
            content = args.get("content_markdown")
            if filename is None or content is None:
                return {"error": "missing required argument: filename/content_markdown"}
            target = sandbox.resolve(filename, must_exist=False)
            from app.word_document import create_document
            return {"tool": tool,
                    "result": create_document(str(target), content)}
        elif tool == "word_append":
            filename = args.get("filename")
            content = args.get("content_markdown")
            if filename is None or content is None:
                return {"error": "missing required argument: filename/content_markdown"}
            target = sandbox.resolve(filename, must_exist=False)
            from app.word_document import append_to_document
            return {"tool": tool,
                    "result": append_to_document(str(target), content)}
        elif tool == "inspect_image_spacing":
            from app.image_spacing import inspect_spacing
            pairs = args.get("pairs") or []
            image_paths = []
            for pair in pairs:
                rel = pair.get("image_path") if isinstance(pair, dict) else None
                if not rel:
                    return {"error": "pair missing image_path"}
                image_paths.append(str(sandbox.resolve(rel, must_exist=False)))
            result = inspect_spacing(str(sandbox.root), image_paths=image_paths or None)
            return {"tool": tool, "result": result}
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
            resume=not pending.get("force_rerun", False),
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
    "resumed",
    "n_skipped",
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
            # 旧会话的 pending 可能没有超参字段：缺省回退默认值
            max_lasso_features=pending.get("max_lasso_features") or 100,
            n_splits=pending.get("n_splits") or 5,
            random_state=(pending.get("random_state")
                          if pending.get("random_state") is not None else 42),
            project_path=project_path,
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


def _run_feature_statistics(
    pending: dict,
    project_path: str,
) -> dict:
    """执行已确认的影像组学特征统计分析任务。"""
    from app.feature_statistics import run_feature_statistics
    sandbox = Sandbox(project_path)
    try:
        feature_csv = _resolve_within_project(sandbox, pending.get("feature_csv"))
        clinical = _resolve_within_project(sandbox, pending.get("clinical"))
        selected_features_csv = _resolve_within_project(
            sandbox, pending.get("selected_features_csv"))
        output_dir = _resolve_within_project(
            sandbox,
            pending.get("output_dir") or str(Path(project_path) / "feature_statistics"),
        )
        result = run_feature_statistics(
            feature_csv=feature_csv,
            clinical=clinical,
            id_col=pending.get("id_col", "patient_id"),
            label_col=pending.get("label_col", "label"),
            selected_features=pending.get("selected_features", []),
            output_dir=output_dir,
        )
        return _json_safe_stats_result(result)
    except PathEscapeError:
        return {"success": False, "error": "路径超出项目目录"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _json_safe_stats_result(result: dict) -> dict:
    """统计分析结果转 JSON 安全摘要：剔除 results 大数组以节省上下文。"""
    return {
        "success": result.get("success", False),
        "message": result.get("message", ""),
        "n_features_analyzed": result.get("n_features_analyzed", 0),
        "n_significant_ttest": result.get("n_significant_ttest", 0),
        "n_significant_mwu": result.get("n_significant_mwu", 0),
        "n_missing_features": result.get("n_missing_features", 0),
        "outputs": result.get("outputs", {}),
    }


# 结果解读：在项目中定位分析输出目录的扫描深度（与分析输入扫描一致）。
_INTERPRETATION_SCAN_DEPTH = 2


def _find_latest_analysis_dir(project_path: str) -> Optional[str]:
    """在项目内定位最新一次分析的输出目录（含 analysis_result.json）。

    不接受用户传入路径；多个候选按文件修改时间取最新，找不到返回 None。
    """
    candidates = []
    for dirpath, dirnames, filenames in os.walk(project_path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        depth = len(Path(dirpath).relative_to(project_path).parts)
        if depth >= _INTERPRETATION_SCAN_DEPTH:
            del dirnames[:]
        if "analysis_result.json" in filenames:
            candidates.append(os.path.join(dirpath, "analysis_result.json"))
    if not candidates:
        return None
    latest = max(candidates, key=os.path.getmtime)
    return os.path.dirname(latest)


def _run_interpretation(
    state: AgentState,
    config: Optional[RunnableConfig] = None,
) -> dict:
    """免确认执行结果解读：定位最新分析输出目录，生成 LLM 解读并注入报告。

    任何失败（无 API key、LLM 异常、返回格式异常、旧输出目录缺
    analysis_result.json）都优雅返回错误说明，不影响既有产物。
    """
    from app.interpretation import apply_to_reports, build_summary, interpret
    from app.llm import LLMClient

    project_path = state["project_path"]
    try:
        output_dir = _find_latest_analysis_dir(project_path)
        if output_dir is None:
            return {
                "success": False,
                "error": "未找到 analysis_result.json：请先运行 "
                         "run_radiomics_analysis 完成一次分析"
                         "（旧版输出目录缺少该文件，需重新运行分析）。",
            }
        result_path = os.path.join(output_dir, "analysis_result.json")
        with open(result_path, "r", encoding="utf-8") as f:
            analysis_result = json.load(f)

        summary = build_summary(analysis_result, output_dir)
        api_key = _resolve_api_key(state, config)
        llm_client = LLMClient(
            api_key=api_key or None,
            base_url=state.get("base_url") or "https://api.deepseek.com/v1",
        )
        interpretation = interpret(summary, llm_client)
        reports = apply_to_reports(analysis_result, output_dir, interpretation)

        interpretation_path = os.path.join(output_dir, "interpretation.md")
        with open(interpretation_path, "w", encoding="utf-8") as f:
            f.write("# 结果解读\n\n")
            for key, title in (("performance", "模型性能解读"),
                               ("features", "特征意义解读"),
                               ("shap", "SHAP 可解释性解读")):
                f.write(f"## {title}\n\n{interpretation.get(key, '')}\n\n")

        return {
            "success": True,
            "message": "结果解读已生成并注入 report.md 与 report.docx",
            "output_dir": output_dir,
            "section_previews": {
                k: v[:200] for k, v in interpretation.items()},
            "outputs": {
                "report_md": reports["report_md"],
                "report_docx": reports["report_docx"],
                "interpretation": interpretation_path,
            },
        }
    except Exception as e:
        logger.warning("结果解读失败", exc_info=True)
        return {
            "success": False,
            "error": f"结果解读失败: {e}（基础报告与既有产物不受影响，可稍后重试）",
        }


def _run_reformat_report(state: AgentState) -> dict:
    """免确认重排最新分析输出目录中的 AutoRadiomics_Report.docx。

    幂等：重复执行结果一致；重排前自动备份原文件为 .bak.docx。
    任何失败都优雅返回错误说明，不影响既有产物。
    """
    from app.docx_style import reformat_docx

    project_path = state["project_path"]
    try:
        output_dir = _find_latest_analysis_dir(project_path)
        if output_dir is None:
            return {
                "success": False,
                "error": "未找到 analysis_result.json：请先运行 "
                         "run_radiomics_analysis 完成一次分析。",
            }
        report_path = os.path.join(output_dir, "AutoRadiomics_Report.docx")
        if not os.path.exists(report_path):
            return {
                "success": False,
                "error": f"报告不存在: {report_path}，请先生成报告。",
            }
        backup = reformat_docx(report_path)
        return {
            "success": True,
            "message": "报告已按中文学术论文格式重排",
            "report_path": report_path,
            "backup": backup,
        }
    except Exception as e:
        logger.warning("报告重排失败", exc_info=True)
        return {"success": False, "error": f"报告重排失败: {e}"}


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
        "pending_feature_statistics": None,
        "script_risk_level": None,
        "confirmed": None,
        "other_instruction": None,
        "pending_subagent": None,
        "pending_choice": None,
        "choice_answer": None,
    })
    return updates
