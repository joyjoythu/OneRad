import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import gradio as gr
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.agent import build_initial_state, create_agent_graph


graph = create_agent_graph()


def _rows_from_plan(plan: List[Dict[str, Any]]) -> List[List[str]]:
    rows = []
    for item in plan or []:
        rows.append(
            [
                str(item.get("action", "")),
                str(item.get("source", "")),
                str(item.get("target", "")),
                str(item.get("reason", "")),
            ]
        )
    return rows


def _plan_from_rows(rows: List[List[Any]]) -> List[Dict[str, Any]]:
    plan = []
    headers = ["action", "source", "target", "reason"]
    for row in rows or []:
        if not row:
            continue
        item = {}
        for i, key in enumerate(headers):
            item[key] = str(row[i]) if i < len(row) else ""
        plan.append(item)
    return plan


def _render_chat(messages: List[Any]) -> List[List[str]]:
    history: List[List[str]] = []
    for msg in messages or []:
        if isinstance(msg, HumanMessage):
            history.append(["user", str(msg.content)])
        elif isinstance(msg, AIMessage):
            history.append(["assistant", str(msg.content)])
        elif isinstance(msg, ToolMessage):
            if history and history[-1][0] == "assistant":
                history[-1][1] += f"\n\n[工具结果]\n{msg.content}"
            else:
                history.append(["assistant", f"[工具结果]\n{msg.content}"])
    return history


def _sync_outputs(snapshot: Any, thread_state: Dict[str, Any], extra_log: str = ""):
    values = getattr(snapshot, "values", {}) or {}
    interrupt_type = values.get("interrupt_type")

    chat_history = _render_chat(values.get("messages", []))

    plan_visible = gr.update(visible=False)
    plan_rows: List[List[str]] = []
    cmd_visible = gr.update(visible=False)
    cmd_text = ""
    script_visible = gr.update(visible=False)
    script_text = ""

    if interrupt_type == "file_plan":
        plan_visible = gr.update(visible=True)
        pending_plan = values.get("pending_plan") or {}
        plan_rows = _rows_from_plan(pending_plan.get("plan", []))
    elif interrupt_type == "system_command":
        cmd_visible = gr.update(visible=True)
        cmd_text = f"```json\n{json.dumps(values.get('pending_command'), ensure_ascii=False, indent=2)}\n```"
    elif interrupt_type == "python_script":
        script_visible = gr.update(visible=True)
        pending_script = values.get("pending_script") or {}
        script_path = pending_script.get("script_path")
        if script_path and Path(script_path).exists():
            try:
                script_text = Path(script_path).read_text(encoding="utf-8")
            except Exception as e:
                script_text = f"# 无法读取脚本: {e}"
        else:
            script_text = "# 脚本文件未找到"

    log_lines = list(values.get("operation_log", []))
    if interrupt_type:
        log_lines.append(f"[中断] 类型: {interrupt_type}")
    if extra_log:
        log_lines.append(extra_log)
    log_text = "\n".join(log_lines) if log_lines else "就绪"

    return (
        chat_history,
        plan_visible,
        plan_rows,
        cmd_visible,
        cmd_text,
        script_visible,
        script_text,
        log_text,
        thread_state,
    )


def _empty_sync(thread_state: Dict[str, Any], log_text: str = ""):
    return (
        [],
        gr.update(visible=False),
        [],
        gr.update(visible=False),
        "",
        gr.update(visible=False),
        "",
        log_text,
        thread_state,
    )


def create_agent_tab(store, current_project_id_state):
    agent_thread_state = gr.State({"thread_id": None, "project_id": None})

    with gr.Tab("AI Agent") as tab:
        chatbot = gr.Chatbot(label="AI Agent", height=400)
        msg_input = gr.Textbox(
            label="输入需求",
            lines=2,
            placeholder="例如：把 test 目录下的 .txt 文件复制到 backup 目录",
        )
        send_btn = gr.Button("发送")

        with gr.Column(visible=False) as plan_panel:
            gr.Markdown("### 待确认的文件操作计划")
            plan_df = gr.Dataframe(
                headers=["action", "source", "target", "reason"],
                datatype=["str", "str", "str", "str"],
                row_count=(0, "dynamic"),
                interactive=True,
                label="计划",
            )
            with gr.Row():
                plan_confirm = gr.Button("确认执行", variant="primary")
                plan_cancel = gr.Button("取消")

        with gr.Column(visible=False) as cmd_panel:
            gr.Markdown("### 待确认的系统命令")
            cmd_md = gr.Markdown()
            with gr.Row():
                cmd_confirm = gr.Button("确认")
                cmd_cancel = gr.Button("取消")

        with gr.Column(visible=False) as script_panel:
            gr.Markdown("### 待确认的 Python 脚本")
            script_code = gr.Code(language="python", label="脚本代码")
            with gr.Row():
                script_confirm = gr.Button("确认执行", variant="primary")
                script_cancel = gr.Button("取消")

        agent_log = gr.Textbox(label="Agent 日志", lines=10, interactive=False)

    outputs = [
        chatbot,
        plan_panel,
        plan_df,
        cmd_panel,
        cmd_md,
        script_panel,
        script_code,
        agent_log,
        agent_thread_state,
    ]

    def on_send(project_id, msg, thread_state):
        if not project_id:
            return _empty_sync(thread_state, "请先选择一个项目")

        if thread_state.get("thread_id") is None or thread_state.get("project_id") != project_id:
            thread_id = str(uuid.uuid4())
            thread_state = {"thread_id": thread_id, "project_id": project_id}
            project = store.load_project(project_id)
            init_state = build_initial_state(project)
            config = {"configurable": {"thread_id": thread_id}}
            graph.update_state(config, init_state)
        else:
            config = {"configurable": {"thread_id": thread_state["thread_id"]}}

        for _ in graph.stream(
            {"messages": [HumanMessage(content=msg)]},
            config,
            stream_mode="values",
        ):
            pass

        snapshot = graph.get_state(config)
        return _sync_outputs(snapshot, thread_state)

    def on_confirm_plan(plan_df_value, thread_state):
        thread_id = thread_state.get("thread_id")
        if not thread_id:
            return _empty_sync(thread_state, "Agent 线程未初始化")
        config = {"configurable": {"thread_id": thread_id}}

        snapshot = graph.get_state(config)
        pending_plan = (getattr(snapshot, "values", {}) or {}).get("pending_plan") or {}
        edited_rows = plan_df_value.values.tolist() if isinstance(plan_df_value, pd.DataFrame) else (plan_df_value or [])
        pending_plan["plan"] = _plan_from_rows(edited_rows)
        graph.update_state(config, {"pending_plan": pending_plan})

        for _ in graph.stream(Command(resume={"action": "confirm"}), config, stream_mode="values"):
            pass
        snapshot = graph.get_state(config)
        return _sync_outputs(snapshot, thread_state)

    def on_resume(thread_state, action: str):
        thread_id = thread_state.get("thread_id")
        if not thread_id:
            return _empty_sync(thread_state, "Agent 线程未初始化")
        config = {"configurable": {"thread_id": thread_id}}
        for _ in graph.stream(Command(resume={"action": action}), config, stream_mode="values"):
            pass
        snapshot = graph.get_state(config)
        return _sync_outputs(snapshot, thread_state)

    send_btn.click(
        on_send,
        inputs=[current_project_id_state, msg_input, agent_thread_state],
        outputs=outputs,
    )
    plan_confirm.click(
        on_confirm_plan,
        inputs=[plan_df, agent_thread_state],
        outputs=outputs,
    )
    plan_cancel.click(
        lambda ts: on_resume(ts, "cancel"),
        inputs=[agent_thread_state],
        outputs=outputs,
    )
    cmd_confirm.click(
        lambda ts: on_resume(ts, "confirm"),
        inputs=[agent_thread_state],
        outputs=outputs,
    )
    cmd_cancel.click(
        lambda ts: on_resume(ts, "cancel"),
        inputs=[agent_thread_state],
        outputs=outputs,
    )
    script_confirm.click(
        lambda ts: on_resume(ts, "confirm"),
        inputs=[agent_thread_state],
        outputs=outputs,
    )
    script_cancel.click(
        lambda ts: on_resume(ts, "cancel"),
        inputs=[agent_thread_state],
        outputs=outputs,
    )

    return tab
