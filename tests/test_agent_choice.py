import json
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from app.agent.tools import build_tools
from app.agent.nodes import process_tool_calls, execute_confirmed, route_after_process


def _make_state(tmp_path, tool_args):
    return {
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "ask_user_choice",
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


ARGS = {"question": "选择哪种重采样方案？", "options": ["1mm", "3mm", "保持原样"]}


def test_ask_user_choice_registered(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    assert "ask_user_choice" in tools


def test_ask_user_choice_not_registered_in_readonly_mode(tmp_path):
    """explore 子 agent（readonly）不向用户提问，不应注册该工具。"""
    tools = build_tools(str(tmp_path), MagicMock(), readonly=True)
    assert "ask_user_choice" not in tools


def test_ask_user_choice_returns_pending_payload(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["ask_user_choice"].invoke(ARGS)
    data = json.loads(result)
    assert data["_pending_tool"] == "ask_user_choice"
    assert data["question"] == "选择哪种重采样方案？"
    assert data["options"] == ["1mm", "3mm", "保持原样"]


def test_ask_user_choice_strips_blank_options_and_caps_at_eight(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["ask_user_choice"].invoke({
        "question": "q",
        "options": ["a", "  ", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
    })
    data = json.loads(result)
    assert data["options"] == ["a", "b", "c", "d", "e", "f", "g", "h"]


def test_ask_user_choice_rejects_fewer_than_two_options(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["ask_user_choice"].invoke({"question": "q", "options": ["只有一个"]})
    data = json.loads(result)
    assert data["success"] is False


def test_process_tool_calls_sets_user_choice_interrupt(tmp_path):
    state = _make_state(tmp_path, ARGS)
    updates = process_tool_calls(state, {"configurable": {}})
    assert updates["interrupt_type"] == "user_choice"
    assert updates["pending_choice"]["tool_call_id"] == "tc1"
    assert updates["pending_choice"]["question"] == ARGS["question"]
    assert updates["pending_choice"]["options"] == ARGS["options"]
    # 待确认工具不生成 ToolMessage，等用户回答后由 execute_confirmed 补齐。
    assert updates["messages"] == []


def test_route_after_process_never_auto_approves_user_choice():
    """自动审批开启时提问也必须等待真实用户回答。"""
    state = {"interrupt_type": "user_choice"}
    assert route_after_process(state, {"configurable": {"auto_approve": True}}) == "human_review"
    assert route_after_process(state, {"configurable": {}}) == "human_review"


def _confirmed_state(tmp_path, **overrides):
    state = {
        "messages": [],
        "project_path": str(tmp_path),
        "interrupt_type": "user_choice",
        "pending_choice": {
            "tool_call_id": "tc1",
            "question": ARGS["question"],
            "options": ARGS["options"],
        },
        "confirmed": True,
        "choice_answer": "3mm",
        "other_instruction": None,
        "tool_outputs": [],
        "operation_log": [],
    }
    state.update(overrides)
    return state


def test_execute_confirmed_returns_answer_as_tool_result(tmp_path):
    updates = execute_confirmed(_confirmed_state(tmp_path), {"configurable": {}})
    assert updates["interrupt_type"] is None
    assert updates["pending_choice"] is None
    assert updates["choice_answer"] is None
    assert len(updates["messages"]) == 1
    msg = updates["messages"][0]
    assert msg.tool_call_id == "tc1"
    payload = json.loads(msg.content)
    assert payload["answer"] == "3mm"


def test_execute_confirmed_cancel_path_for_user_choice(tmp_path):
    updates = execute_confirmed(
        _confirmed_state(tmp_path, confirmed=False, choice_answer=None),
        {"configurable": {}},
    )
    payload = json.loads(updates["messages"][0].content)
    assert payload["cancelled"] is True
    assert "answer" not in payload
