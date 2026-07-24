import json
from unittest.mock import MagicMock

import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from app.agent.tools import build_tools
from app.agent.nodes import _run_system_command, process_tool_calls


def _pending(args):
    return {"_pending_tool": "read_tabular_file", "args": args}


def _make_state(tmp_path, tool_args):
    return {
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "read_tabular_file",
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


def test_read_tabular_file_registered(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    assert "read_tabular_file" in tools


def test_read_tabular_file_registered_in_readonly_mode(tmp_path):
    """explore 子 agent（readonly）也应能使用该工具。"""
    tools = build_tools(str(tmp_path), MagicMock(), readonly=True)
    assert "read_tabular_file" in tools


def test_read_tabular_file_returns_pending(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["read_tabular_file"].invoke({"path": "data.csv"})
    data = json.loads(result)
    assert data["_pending_tool"] == "read_tabular_file"
    assert data["args"]["path"] == "data.csv"


def test_process_tool_calls_readonly_executes_without_interrupt(tmp_path):
    """只读工具免确认：不触发中断，直接在本节点执行并返回结果。"""
    pd.DataFrame({"a": [1, 2]}).to_csv(tmp_path / "data.csv", index=False)
    state = _make_state(tmp_path, {"path": "data.csv"})
    updates = process_tool_calls(state, {"configurable": {}})
    assert updates["interrupt_type"] is None
    assert updates.get("pending_command") is None
    tool_msg = updates["messages"][0]
    assert tool_msg.tool_call_id == "tc1"
    parsed = json.loads(tool_msg.content)
    assert parsed["tool"] == "read_tabular_file"
    assert parsed["result"]["shape"] == [2, 1]


def test_run_system_command_reads_csv_preview(tmp_path):
    df = pd.DataFrame({"a": range(50), "b": [f"x{i}" for i in range(50)]})
    df.to_csv(tmp_path / "data.csv", index=False, encoding="utf-8")
    result = _run_system_command(
        _pending({"path": "data.csv", "head": 5}), str(tmp_path)
    )
    assert "error" not in result
    payload = result["result"]
    assert payload["shape"] == [50, 2]
    assert [c["name"] for c in payload["columns"]] == ["a", "b"]
    assert len(payload["head_rows"]) == 5
    assert payload["head_rows"][0]["a"] == 0
    assert payload["truncated"] is True


def test_run_system_command_reads_gbk_csv(tmp_path):
    df = pd.DataFrame({"姓名": ["张三", "李四"], "年龄": [30, 40]})
    df.to_csv(tmp_path / "gbk.csv", index=False, encoding="gbk")
    result = _run_system_command(_pending({"path": "gbk.csv"}), str(tmp_path))
    assert "error" not in result
    payload = result["result"]
    assert [c["name"] for c in payload["columns"]] == ["姓名", "年龄"]
    assert payload["head_rows"][0]["姓名"] == "张三"


def test_run_system_command_reads_excel_with_sheet(tmp_path):
    with pd.ExcelWriter(tmp_path / "book.xlsx") as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="First", index=False)
        pd.DataFrame({"b": [2, 3]}).to_excel(writer, sheet_name="Second", index=False)
    result = _run_system_command(
        _pending({"path": "book.xlsx", "sheet_name": "Second"}), str(tmp_path)
    )
    assert "error" not in result
    payload = result["result"]
    assert payload["shape"] == [2, 1]
    assert [c["name"] for c in payload["columns"]] == ["b"]


def test_run_system_command_head_zero_returns_structure_only(tmp_path):
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(tmp_path / "data.csv", index=False)
    result = _run_system_command(
        _pending({"path": "data.csv", "head": 0}), str(tmp_path)
    )
    assert "error" not in result
    payload = result["result"]
    assert payload["shape"] == [3, 1]
    assert payload["head_rows"] == []


def test_run_system_command_columns_selection(tmp_path):
    pd.DataFrame({"a": [1], "b": [2], "c": [3]}).to_csv(
        tmp_path / "data.csv", index=False
    )
    result = _run_system_command(
        _pending({"path": "data.csv", "columns": ["a", "c"]}), str(tmp_path)
    )
    assert "error" not in result
    payload = result["result"]
    assert [c["name"] for c in payload["columns"]] == ["a", "c"]
    assert payload["head_rows"] == [{"a": 1, "c": 3}]


def test_run_system_command_unknown_column_error(tmp_path):
    pd.DataFrame({"a": [1]}).to_csv(tmp_path / "data.csv", index=False)
    result = _run_system_command(
        _pending({"path": "data.csv", "columns": ["nope"]}), str(tmp_path)
    )
    assert "error" in result
    assert "nope" in result["error"]


def test_run_system_command_rejects_unsupported_extension(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    result = _run_system_command(_pending({"path": "notes.txt"}), str(tmp_path))
    assert "error" in result


def test_run_system_command_rejects_path_outside_project(tmp_path):
    result = _run_system_command(_pending({"path": "../secret.csv"}), str(tmp_path))
    assert "error" in result
