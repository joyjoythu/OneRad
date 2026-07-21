import json
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from app.agent.tools import build_tools
from app.agent.nodes import process_tool_calls


def _make_state(tmp_path, tool_args):
    return {
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "update_todo_list",
            "args": tool_args,
            "id": "tc1",
        }])],
        "project_path": str(tmp_path),
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "test-key",
        "model": "deepseek-v4-pro",
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "confirmed": None,
        "tool_outputs": [],
        "operation_log": [],
    }


TODOS = [
    {"content": "项目勘察", "status": "completed"},
    {"content": "配对发现", "status": "in_progress"},
    {"content": "特征提取", "status": "pending"},
]


def test_update_todo_list_registered(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    assert "update_todo_list" in tools


def test_update_todo_list_not_registered_in_readonly_mode(tmp_path):
    """explore 子 agent（readonly）不需要计划面板工具。"""
    tools = build_tools(str(tmp_path), MagicMock(), readonly=True)
    assert "update_todo_list" not in tools


def test_update_todo_list_normalizes_items(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["update_todo_list"].invoke({"todos": TODOS + [
        {"content": "  ", "status": "pending"},          # 空 content 丢弃
        {"content": "报告", "status": "done"},             # 非法 status 回落 pending
        "not-a-dict",                                       # 非 dict 丢弃
    ]})
    data = json.loads(result)
    assert data["success"] is True
    assert data["todos"] == TODOS + [{"content": "报告", "status": "pending"}]


def test_update_todo_list_preserves_cancelled(tmp_path):
    """stop 定格的 cancelled 步骤在模型全量回传列表时应原样保留。"""
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["update_todo_list"].invoke({"todos": [
        {"content": "项目勘察", "status": "completed"},
        {"content": "特征提取", "status": "cancelled"},
    ]})
    data = json.loads(result)
    assert data["success"] is True
    assert data["todos"] == [
        {"content": "项目勘察", "status": "completed"},
        {"content": "特征提取", "status": "cancelled"},
    ]


def test_update_todo_list_rejects_empty(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["update_todo_list"].invoke({"todos": []})
    data = json.loads(result)
    assert data["success"] is False


def test_process_tool_calls_writes_todos_without_interrupt(tmp_path):
    """免确认：直接写 state.todos，不设置 interrupt，记录操作日志。"""
    state = _make_state(tmp_path, {"todos": TODOS})
    updates = process_tool_calls(state, {"configurable": {}})
    assert updates.get("interrupt_type") is None
    assert updates["todos"] == TODOS
    assert any(
        isinstance(log, dict) and log["text"] == "计划面板已更新（1/3 已完成）" and log["time"]
        for log in updates["operation_log"]
    )
    assert len(updates["messages"]) == 1
    assert updates["messages"][0].tool_call_id == "tc1"


def test_process_tool_calls_tool_error_keeps_state_untouched(tmp_path):
    state = _make_state(tmp_path, {"todos": []})
    updates = process_tool_calls(state, {"configurable": {}})
    assert "todos" not in updates
    assert len(updates["messages"]) == 1
