import os
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.agent.nodes import _build_llm, _resolve_api_key, call_llm
from app.agent.state import AgentState


def _make_state(api_key: str = "") -> AgentState:
    return {
        "messages": [],
        "project_path": "/tmp/project",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": api_key,
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


def test_resolve_api_key_prefers_config():
    state = _make_state(api_key="state-key")
    config = {"configurable": {"api_key": "config-key"}}
    assert _resolve_api_key(state, config) == "config-key"


def test_resolve_api_key_falls_back_to_state():
    state = _make_state(api_key="state-key")
    assert _resolve_api_key(state) == "state-key"


def test_resolve_api_key_falls_back_to_openai_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    state = _make_state()
    assert _resolve_api_key(state) == "openai-env-key"


def test_resolve_api_key_falls_back_to_deepseek_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-env-key")
    state = _make_state()
    assert _resolve_api_key(state) == "deepseek-env-key"


def test_resolve_api_key_prefers_openai_over_deepseek_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-env-key")
    state = _make_state()
    assert _resolve_api_key(state) == "openai-env-key"


def test_resolve_api_key_returns_empty_when_nothing_available(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    state = _make_state()
    assert _resolve_api_key(state) == ""


def test_build_llm_uses_explicit_api_key():
    state = _make_state()
    llm = _build_llm("explicit-key", state)
    assert llm.openai_api_key.get_secret_value() == "explicit-key"


def test_build_llm_does_not_override_env_with_empty_string(monkeypatch):
    """空 api_key 不应覆盖 OPENAI_API_KEY 等环境变量。

    之前传入空字符串会导致 ChatOpenAI 在构造时抛出 Missing credentials。
    """
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    state = _make_state()
    # 构造时不应报错
    llm = _build_llm("", state)
    assert llm.openai_api_key is None


def test_build_llm_uses_config_model():
    state = _make_state()
    config = {"configurable": {"llm_model": "deepseek-v4-flash"}}
    llm = _build_llm("key", state, config)
    assert llm.model_name == "deepseek-v4-flash"


def test_build_llm_falls_back_to_state_model():
    state = _make_state()
    llm = _build_llm("key", state)
    assert llm.model_name == "deepseek-v4-pro"


def test_call_llm_records_context_usage(tmp_path):
    """call_llm 应从响应的 usage_metadata 提取 token 用量写入 state 更新。"""
    state = _make_state()
    state["project_path"] = str(tmp_path)
    ai = AIMessage(
        content="Hi",
        usage_metadata={"input_tokens": 1234, "output_tokens": 56, "total_tokens": 1290},
    )
    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = ai
        mock_llm_class.return_value = mock_llm
        result = call_llm(state)

    assert result["messages"] == [ai]
    assert result["context_usage"] == {
        "input_tokens": 1234,
        "output_tokens": 56,
        "total_tokens": 1290,
    }


def test_call_llm_omits_context_usage_when_api_returns_none(tmp_path):
    """API 未返回 usage_metadata 时不更新该字段（保留旧值）。"""
    state = _make_state()
    state["project_path"] = str(tmp_path)
    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="Hi")  # usage_metadata=None
        mock_llm_class.return_value = mock_llm
        result = call_llm(state)

    assert "context_usage" not in result
