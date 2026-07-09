import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage
from app.agent.tools import build_tools
from app.agent.safety import Sandbox


def test_list_directory_tool_schema(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    assert "list_directory" in tools
    assert "find_files" in tools
    assert "get_file_info" in tools
    assert "plan_file_operations" in tools
    assert "execute_python_script" in tools


def test_list_directory_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["list_directory"].invoke({"path": "sub"})
    data = __import__("json").loads(result)
    assert data["_pending_tool"] == "list_directory"


def test_execute_python_script_rejects_high_risk(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "import os\nos.system('ls')"
    result = tools["execute_python_script"].invoke(
        {"description": "high risk test", "code": code}
    )
    data = __import__("json").loads(result)
    assert data["error"] == "脚本被判定为高风险，拒绝执行"
    assert data["risk_level"] == "high"


def test_execute_python_script_returns_medium_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "with open('test.txt', 'w') as f:\n    f.write('hello')"
    result = tools["execute_python_script"].invoke(
        {"description": "medium risk test", "code": code}
    )
    data = __import__("json").loads(result)
    assert data["_pending_tool"] == "execute_python_script"
    assert data["script"]["risk_level"] == "medium"


def test_execute_python_script_runs_low_risk(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "print('hello from agent tool')"
    result = tools["execute_python_script"].invoke(
        {"description": "low risk test", "code": code}
    )
    data = __import__("json").loads(result)
    assert data["success"] is True
    assert "hello from agent tool" in data["stdout"]
