import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.agent.nodes import _build_llm, _resolve_api_key, auto_confirm, call_llm, route_after_process
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


def _tc_delta(index, id=None, name=None, arguments=None):
    """构造一个 openai SDK 流式 tool_calls delta。"""
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _chunk(content=None, reasoning=None, tool_calls=None, usage=None):
    """构造一个 openai SDK 流式响应 chunk。"""
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=tool_calls or [],
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def _patch_openai_stream(chunks):
    """patch app.agent.nodes.OpenAI，使其 chat.completions.create 返回给定 chunk 流。"""
    mock_openai = patch("app.agent.nodes.OpenAI")
    mock_cls = mock_openai.start()
    client = MagicMock()
    client.chat.completions.create.return_value = iter(chunks)
    mock_cls.return_value.__enter__.return_value = client
    return mock_openai, client


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


def test_build_llm_ignores_legacy_config_model():
    state = _make_state()
    config = {"configurable": {"llm_model": "deepseek-v4-pro"}}
    llm = _build_llm("key", state, config)
    assert llm.model_name == "deepseek-v4-flash"


def test_build_llm_ignores_legacy_state_model():
    state = _make_state()
    llm = _build_llm("key", state)
    assert llm.model_name == "deepseek-v4-flash"


def test_call_llm_streams_reasoning_and_publishes_thinking(tmp_path):
    """reasoning_content delta 累积进 additional_kwargs，并逐次推送 thinking 事件。"""
    state = _make_state(api_key="test-key")
    state["project_path"] = str(tmp_path)
    chunks = [
        _chunk(reasoning="先分析"),
        _chunk(reasoning="再回答"),
        _chunk(content="你好"),
        _chunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)),
    ]
    mock_openai, _ = _patch_openai_stream(chunks)
    try:
        with patch("app.agent.nodes._publish_thinking") as mock_pub:
            result = call_llm(state, {"configurable": {"thread_id": "t1"}})
    finally:
        mock_openai.stop()

    ai = result["messages"][0]
    assert ai.content == "你好"
    assert ai.additional_kwargs["reasoning_content"] == "先分析再回答"
    assert result["context_usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    # 推送时序：重置 → 逐次累积 → done
    calls = [c.args for c in mock_pub.call_args_list]
    assert calls[0] == ("t1", "", False)
    assert ("t1", "先分析", False) in calls
    assert ("t1", "先分析再回答", False) in calls
    assert calls[-1] == ("t1", "先分析再回答", True)


def test_call_llm_accumulates_tool_call_deltas(tmp_path):
    """tool_calls 的 id/name/arguments 按 index 跨 chunk 拼接，arguments 解析为 dict。"""
    state = _make_state(api_key="test-key")
    state["project_path"] = str(tmp_path)
    chunks = [
        _chunk(tool_calls=[_tc_delta(0, id="call_1", name="list_directory")]),
        _chunk(tool_calls=[_tc_delta(0, arguments='{"path":')]),
        _chunk(tool_calls=[_tc_delta(0, arguments=' "."}')]),
    ]
    mock_openai, _ = _patch_openai_stream(chunks)
    try:
        with patch("app.agent.nodes._publish_thinking"):
            result = call_llm(state)
    finally:
        mock_openai.stop()

    ai = result["messages"][0]
    assert ai.tool_calls == [
        {"name": "list_directory", "args": {"path": "."}, "id": "call_1", "type": "tool_call"}
    ]


def test_call_llm_omits_context_usage_when_stream_has_no_usage(tmp_path):
    """流中没有 usage chunk 时不更新 context_usage（保留旧值）。"""
    state = _make_state(api_key="test-key")
    state["project_path"] = str(tmp_path)
    mock_openai, _ = _patch_openai_stream([_chunk(content="Hi")])
    try:
        with patch("app.agent.nodes._publish_thinking"):
            result = call_llm(state)
    finally:
        mock_openai.stop()

    assert "context_usage" not in result
    ai = result["messages"][0]
    assert "reasoning_content" not in ai.additional_kwargs


def test_call_llm_handles_usage_chunk_with_empty_choices(tmp_path):
    """DeepSeek 的 usage-only chunk choices 为空列表，不得 IndexError，usage 照常记录。"""
    state = _make_state(api_key="test-key")
    state["project_path"] = str(tmp_path)
    chunks = [
        _chunk(content="你好"),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4, total_tokens=12),
        ),
    ]
    mock_openai, _ = _patch_openai_stream(chunks)
    try:
        with patch("app.agent.nodes._publish_thinking"):
            result = call_llm(state)
    finally:
        mock_openai.stop()

    assert result["messages"][0].content == "你好"
    assert result["context_usage"] == {
        "input_tokens": 8,
        "output_tokens": 4,
        "total_tokens": 12,
    }


def test_call_llm_raises_on_invalid_tool_arguments(tmp_path):
    """tool_calls 参数 JSON 解析失败必须抛错，不得带错参数执行工具。"""
    state = _make_state(api_key="test-key")
    state["project_path"] = str(tmp_path)
    chunks = [_chunk(tool_calls=[_tc_delta(0, id="call_1", name="list_directory", arguments="{oops")])]
    mock_openai, _ = _patch_openai_stream(chunks)
    try:
        with patch("app.agent.nodes._publish_thinking"):
            with pytest.raises(ValueError, match="list_directory"):
                call_llm(state)
    finally:
        mock_openai.stop()


def test_call_llm_passes_fixed_model_and_tools_to_api(tmp_path):
    """验证请求参数：固定模型、messages 转为 OpenAI 格式、附带 tools。"""
    state = _make_state(api_key="test-key")
    state["project_path"] = str(tmp_path)
    state["messages"] = [AIMessage(content="之前")]
    mock_openai, client = _patch_openai_stream([_chunk(content="好")])
    try:
        with patch("app.agent.nodes._publish_thinking"):
            call_llm(state, {"configurable": {"llm_model": "deepseek-v4-pro"}})
    finally:
        mock_openai.stop()

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-flash"
    assert kwargs["stream"] is True
    assert kwargs["parallel_tool_calls"] is False
    assert kwargs["messages"] == [{"role": "assistant", "content": "之前"}]
    assert any(t["function"]["name"] == "list_directory" for t in kwargs["tools"])


def test_route_after_process_returns_call_llm_without_interrupt():
    state = {"interrupt_type": None}
    assert route_after_process(state, {"configurable": {}}) == "call_llm"


def test_route_after_process_returns_human_review_by_default():
    state = {"interrupt_type": "system_command"}
    assert route_after_process(state, {"configurable": {}}) == "human_review"


def test_route_after_process_returns_auto_confirm_when_enabled():
    state = {"interrupt_type": "system_command"}
    config = {"configurable": {"auto_approve": True}}
    assert route_after_process(state, config) == "auto_confirm"


def test_auto_confirm_marks_confirmed():
    assert auto_confirm({}) == {"confirmed": True}



def test_publish_thinking_publishes_partial_payload_without_persist():
    """_publish_thinking 经 bridge 发布 partial 载荷且不落库（persist=False）。"""
    import asyncio
    from unittest.mock import AsyncMock
    from app.agent import runtime as agent_runtime
    from app.agent.nodes import _publish_thinking

    loop = asyncio.new_event_loop()
    bridge = MagicMock()
    bridge.publish = AsyncMock()
    agent_runtime.register("t-think", loop=loop, bridge=bridge)
    try:
        _publish_thinking("t-think", "想的内容", False)
        # run_coroutine_threadsafe 已把协程排入 loop；驱动 loop 一次让协程跑到完成
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        agent_runtime.unregister("t-think")
        loop.close()

    bridge.publish.assert_awaited_once_with(
        "agent",
        "t-think",
        {"thinking": {"text": "想的内容", "done": False}, "running": True},
        persist=False,
    )


def test_publish_thinking_noops_without_runtime_context():
    """无运行时上下文（线程未在运行）时静默跳过。"""
    from app.agent.nodes import _publish_thinking

    _publish_thinking("nonexistent-thread", "text", True)  # 不抛异常即通过
