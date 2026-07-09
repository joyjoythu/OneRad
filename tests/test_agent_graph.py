import json
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.types import Command

from app.agent import create_agent_graph, build_initial_state


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

