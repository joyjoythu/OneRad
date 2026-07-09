import json
from typing import Literal
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from app.agent.tools import build_tools
from app.agent.safety import Sandbox
from app.actions import execute_plan
from app.code_runner import execute_script_if_safe


def call_llm(state):
    llm = ChatOpenAI(
        api_key=state["api_key"],
        base_url=state["base_url"],
        model=state["model"],
        temperature=0.2,
    )
    tools = build_tools(state["project_path"], llm)
    model_with_tools = llm.bind_tools(list(tools.values()), parallel_tool_calls=False)
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state) -> Literal["process_tool_calls", "__end__"]:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "process_tool_calls"
    return "__end__"


def process_tool_calls(state):
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", [])
    if not tool_calls:
        return {"interrupt_type": None}

    llm = ChatOpenAI(api_key=state["api_key"], base_url=state["base_url"], model=state["model"], temperature=0.2)
    tools = build_tools(state["project_path"], llm)

    updates = {"messages": []}
    interrupt_type = None

    for tc in tool_calls:
        name = tc["name"]
        args = tc["args"]
        tool_result = tools[name].invoke(args)
        try:
            parsed = json.loads(tool_result)
        except json.JSONDecodeError:
            updates["messages"].append(ToolMessage(
                content=json.dumps({"error": f"Tool {name} returned invalid JSON"}),
                tool_call_id=tc["id"],
            ))
            continue

        if name in {"list_directory", "find_files", "get_file_info"}:
            interrupt_type = "system_command"
            updates["pending_command"] = {"tool_call_id": tc["id"], **parsed}
        elif name == "plan_file_operations":
            interrupt_type = "file_plan"
            updates["pending_plan"] = {"tool_call_id": tc["id"], "plan": parsed}
        elif name == "execute_python_script":
            if "error" in parsed:
                updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))
            elif "_pending_tool" in parsed:
                interrupt_type = "python_script"
                updates["pending_script"] = {"tool_call_id": tc["id"], **parsed["script"]}
                updates["script_risk_level"] = parsed["script"]["risk_level"]
            else:
                updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))
        else:
            updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))

    updates["interrupt_type"] = interrupt_type
    return updates


def route_after_process(state) -> Literal["human_review", "call_llm"]:
    return "human_review" if state.get("interrupt_type") else "call_llm"


def human_review(state):
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


def execute_confirmed(state):
    itype = state["interrupt_type"]
    if itype == "file_plan":
        tool_call_id = state["pending_plan"]["tool_call_id"]
    elif itype == "system_command":
        tool_call_id = state["pending_command"]["tool_call_id"]
    elif itype == "python_script":
        tool_call_id = state["pending_script"]["tool_call_id"]
    else:
        tool_call_id = ""

    if not state.get("confirmed"):
        content = json.dumps({"cancelled": True, "reason": "用户取消了操作"})
        return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]}, state)

    if itype == "file_plan":
        results = execute_plan(state["pending_plan"]["plan"], state["project_path"])
    elif itype == "system_command":
        results = _run_system_command(state["pending_command"], state["project_path"])
    elif itype == "python_script":
        results = execute_script_if_safe(state["pending_script"], state["project_path"])
    else:
        results = {"error": "unknown interrupt type"}

    content = json.dumps(results)
    return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]}, state)


def _run_system_command(command: dict, project_path: str) -> dict:
    tool = command.get("_pending_tool") or command.get("tool")
    args = command.get("args", {})
    sandbox = Sandbox(project_path)
    try:
        if tool == "list_directory":
            target = sandbox.resolve(args["path"])
            entries = [f"{'D' if e.is_dir() else 'F'} {e.name}" for e in sorted(target.iterdir())]
            return {"tool": tool, "result": "\n".join(entries)}
        elif tool == "find_files":
            target = sandbox.resolve(args.get("path", "."))
            matches = list(target.rglob(args["pattern"]))[:100]
            return {"tool": tool, "result": [str(m.relative_to(sandbox.root)) for m in matches]}
        elif tool == "get_file_info":
            target = sandbox.resolve(args["path"], must_exist=True)
            st = target.stat()
            return {"tool": tool, "result": {"path": str(target.relative_to(sandbox.root)), "size": st.st_size, "mtime": st.st_mtime, "is_dir": target.is_dir()}}
        return {"error": f"unknown command {tool}"}
    except Exception as e:
        return {"error": str(e)}


def _clear_interrupt(updates: dict, state: dict) -> dict:
    updates.update({
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "confirmed": None,
    })
    return updates
