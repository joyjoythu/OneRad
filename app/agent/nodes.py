import json
from typing import Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from app.agent.state import AgentState
from app.agent.tools import build_tools
from app.agent.safety import Sandbox
from app.actions import execute_plan
from app.code_runner import execute_script_if_safe


def _build_llm(api_key: str, state: AgentState) -> ChatOpenAI:
    """根据状态构造 ChatOpenAI 实例。"""
    return ChatOpenAI(
        api_key=api_key,
        base_url=state["base_url"],
        model=state["model"],
        temperature=0.2,
    )


def _resolve_api_key(state: AgentState, config: Optional[RunnableConfig] = None) -> str:
    """优先从 RunnableConfig 读取 api_key，兼容旧测试直接传入 state。"""
    if config is not None:
        api_key = config.get("configurable", {}).get("api_key", "")
        if api_key:
            return api_key
    return state.get("api_key", "")


def call_llm(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """调用 LLM，绑定工具后生成回复。"""
    api_key = _resolve_api_key(state, config)
    llm = _build_llm(api_key, state)
    tools = build_tools(state["project_path"], llm)
    model_with_tools = llm.bind_tools(list(tools.values()), parallel_tool_calls=False)
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


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
    llm = _build_llm(api_key, state)
    tools = build_tools(state["project_path"], llm)

    updates = {"messages": []}
    interrupt_type = None

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

        if name in {"list_directory", "find_files", "get_file_info"}:
            interrupt_type = "system_command"
            updates["pending_command"] = {"tool_call_id": tool_call_id, **parsed}
        elif name == "plan_file_operations":
            interrupt_type = "file_plan"
            updates["pending_plan"] = {"tool_call_id": tool_call_id, "plan": parsed}
        elif name == "execute_python_script":
            if isinstance(parsed, dict):
                if "error" in parsed:
                    updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tool_call_id))
                elif "_pending_tool" in parsed and "script" in parsed:
                    interrupt_type = "python_script"
                    updates["pending_script"] = {"tool_call_id": tool_call_id, **parsed["script"]}
                    updates["script_risk_level"] = parsed["script"]["risk_level"]
                else:
                    updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tool_call_id))
            else:
                updates["messages"].append(ToolMessage(
                    content=json.dumps({"error": f"Tool {name} returned non-dict result"}),
                    tool_call_id=tool_call_id,
                ))
        else:
            updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tool_call_id))

    updates["interrupt_type"] = interrupt_type
    return updates


def route_after_process(state: AgentState) -> Literal["human_review", "call_llm"]:
    """根据是否有待确认的中断决定路由。"""
    return "human_review" if state.get("interrupt_type") else "call_llm"


def human_review(state: AgentState) -> dict:
    """通过 interrupt 暂停并等待用户确认、编辑或取消。"""
    value = interrupt({
        "type": state["interrupt_type"],
        "plan": state.get("pending_plan"),
        "command": state.get("pending_command"),
        "script": state.get("pending_script"),
    })
    if not isinstance(value, dict):
        value = {"action": "cancel"}

    pending_plan = state.get("pending_plan")
    if "plan" in value and pending_plan:
        pending_plan = {"tool_call_id": pending_plan["tool_call_id"], "plan": value["plan"]}

    return {
        "confirmed": value.get("action") == "confirm",
        "pending_plan": pending_plan,
    }


def execute_confirmed(state: AgentState) -> dict:
    """根据用户确认结果执行待处理操作或取消，并清空中断状态。"""
    itype = state["interrupt_type"]

    pending_plan = state.get("pending_plan")
    pending_command = state.get("pending_command")
    pending_script = state.get("pending_script")

    if itype == "file_plan":
        if not pending_plan:
            return _clear_interrupt({
                "messages": [ToolMessage(content=json.dumps({"error": "Missing pending plan"}), tool_call_id="")]
            })
        tool_call_id = pending_plan["tool_call_id"]
    elif itype == "system_command":
        if not pending_command:
            return _clear_interrupt({
                "messages": [ToolMessage(content=json.dumps({"error": "Missing pending command"}), tool_call_id="")]
            })
        tool_call_id = pending_command["tool_call_id"]
    elif itype == "python_script":
        if not pending_script:
            return _clear_interrupt({
                "messages": [ToolMessage(content=json.dumps({"error": "Missing pending script"}), tool_call_id="")]
            })
        tool_call_id = pending_script["tool_call_id"]
    else:
        tool_call_id = (
            (pending_plan or {}).get("tool_call_id", "")
            or (pending_command or {}).get("tool_call_id", "")
            or (pending_script or {}).get("tool_call_id", "")
            or ""
        )
        content = json.dumps({"error": f"unknown interrupt type: {itype}"})
        return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    if not state.get("confirmed"):
        content = json.dumps({"cancelled": True, "reason": "用户取消了操作"})
        return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

    if itype == "file_plan":
        results = execute_plan(state["pending_plan"]["plan"], state["project_path"])
    elif itype == "system_command":
        results = _run_system_command(state["pending_command"], state["project_path"])
    elif itype == "python_script":
        results = execute_script_if_safe(state["pending_script"], state["project_path"])
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


def _clear_interrupt(updates: dict) -> dict:
    """清空中断相关状态字段。"""
    updates.update({
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "confirmed": None,
    })
    return updates
