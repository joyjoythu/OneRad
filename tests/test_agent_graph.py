import json
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.types import Command

from app.agent import create_agent_graph, build_initial_state
from app.agent.nodes import process_tool_calls


def _find_tool_message(messages, tool_call_id=None):
    for m in messages:
        if isinstance(m, ToolMessage):
            if tool_call_id is None or m.tool_call_id == tool_call_id:
                return m
    return None


def test_graph_runs_to_end_without_tools(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="hello")]

    graph = create_agent_graph()
    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="Hi there")
        mock_llm_class.return_value = mock_llm

        final = graph.invoke(state, {"configurable": {"thread_id": "test-thread"}})
        assert final["messages"][-1].content == "Hi there"


def test_graph_interrupts_on_system_command(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="list files")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-system-command"}}

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{"name": "list_directory", "args": {"path": "."}, "id": "call_list"}],
            ),
            AIMessage(content="Done"),
        ]
        mock_llm_class.return_value = mock_llm

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    tool_msg = _find_tool_message(final["messages"], tool_call_id="call_list")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed["tool"] == "list_directory"
    assert "result" in parsed


def test_graph_interrupts_on_file_plan(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="organize files")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-file-plan"}}

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        def side_effect(messages):
            # plan_file_operations invokes the LLM with a planning prompt.
            if any(isinstance(m, SystemMessage) for m in messages):
                return AIMessage(
                    content='[{"action": "mkdir", "target": "new_folder", "reason": "create folder"}]'
                )
            # call_llm invocations: first returns the plan tool call, second ends the loop.
            if not hasattr(side_effect, "call_count"):
                side_effect.call_count = 0
            side_effect.call_count += 1
            if side_effect.call_count == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "plan_file_operations",
                        "args": {"instruction": "organize files"},
                        "id": "call_plan",
                    }],
                )
            return AIMessage(content="Done")

        mock_llm.invoke.side_effect = side_effect
        mock_llm_class.return_value = mock_llm

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    tool_msg = _find_tool_message(final["messages"], tool_call_id="call_plan")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed[0]["success"] is True
    assert (tmp_path / "new_folder").is_dir()


def test_graph_cancel_operation(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="list files")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-cancel"}}

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{"name": "list_directory", "args": {"path": "."}, "id": "call_cancel"}],
            ),
            AIMessage(content="Done"),
        ]
        mock_llm_class.return_value = mock_llm

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        final = graph.invoke(Command(resume={"action": "cancel"}), config)

    tool_msg = _find_tool_message(final["messages"], tool_call_id="call_cancel")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed.get("cancelled") is True


def test_graph_cancel_file_plan_does_not_execute(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="organize files")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-cancel-file-plan"}}

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        def side_effect(messages):
            if any(isinstance(m, SystemMessage) for m in messages):
                return AIMessage(
                    content='[{"action": "mkdir", "target": "should_not_exist", "reason": "create folder"}]'
                )
            if not hasattr(side_effect, "call_count"):
                side_effect.call_count = 0
            side_effect.call_count += 1
            if side_effect.call_count == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "plan_file_operations",
                        "args": {"instruction": "organize files"},
                        "id": "call_cancel_plan",
                    }],
                )
            return AIMessage(content="Done")

        mock_llm.invoke.side_effect = side_effect
        mock_llm_class.return_value = mock_llm

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        final = graph.invoke(Command(resume={"action": "cancel"}), config)

    tool_msg = _find_tool_message(final["messages"], tool_call_id="call_cancel_plan")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed.get("cancelled") is True
    assert not (tmp_path / "should_not_exist").exists()


def test_graph_interrupts_on_python_script(tmp_path):
    """中风险 Python 脚本会触发中断，确认后执行并返回结果。"""
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="write a file")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-python-script"}}

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class, \
         patch("app.agent.nodes.execute_script_if_safe") as mock_execute:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "execute_python_script",
                    "args": {
                        "description": "write file",
                        "code": 'with open("out.txt", "w") as f:\n    f.write("hello")\n',
                    },
                    "id": "call_script",
                }],
            ),
            AIMessage(content="Done"),
        ]
        mock_llm_class.return_value = mock_llm
        mock_execute.return_value = {"success": True, "stdout": "hello", "stderr": ""}

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    tool_msg = _find_tool_message(final["messages"], tool_call_id="call_script")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed["success"] is True
    assert parsed["stdout"] == "hello"
    mock_execute.assert_called_once()


def test_graph_interrupts_on_low_risk_python_script(tmp_path):
    """低风险 Python 脚本也会触发中断，确认后执行并返回结果。"""
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="say hello")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-low-risk-python-script"}}

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "execute_python_script",
                    "args": {
                        "description": "say hello",
                        "code": "print('hello')",
                    },
                    "id": "call_low_script",
                }],
            ),
            AIMessage(content="Done"),
        ]
        mock_llm_class.return_value = mock_llm

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    tool_msg = _find_tool_message(final["messages"], tool_call_id="call_low_script")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed["returncode"] == 0
    assert "hello" in parsed["stdout"]


def test_graph_non_dict_resume_defaults_to_cancel(tmp_path):
    """非字典的 resume 值应被视为取消，不产生副作用。"""
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="list files")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-non-dict-resume"}}

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{"name": "list_directory", "args": {"path": "."}, "id": "call_non_dict"}],
            ),
            AIMessage(content="Done"),
        ]
        mock_llm_class.return_value = mock_llm

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        final = graph.invoke(Command(resume="not-a-dict"), config)

    tool_msg = _find_tool_message(final["messages"], tool_call_id="call_non_dict")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed.get("cancelled") is True


def test_process_tool_calls_unknown_tool_returns_error():
    """未知或缺失的工具名应返回错误 ToolMessage。"""
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "nonexistent_tool", "args": {}, "id": "call_unknown"}],
            )
        ],
        "project_path": ".",
        "api_key": "fake",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    }

    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm_class.return_value = MagicMock()
        updates = process_tool_calls(state)

    assert updates["interrupt_type"] is None
    assert len(updates["messages"]) == 1
    tool_msg = updates["messages"][0]
    assert tool_msg.tool_call_id == "call_unknown"
    parsed = json.loads(tool_msg.content)
    assert "error" in parsed
    assert "nonexistent_tool" in parsed["error"]
