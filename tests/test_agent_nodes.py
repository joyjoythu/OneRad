import json
import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.nodes import (
    _build_llm,
    _resolve_api_key,
    _run_system_command,
    auto_confirm,
    call_llm,
    execute_confirmed,
    human_review,
    route_after_process,
)
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
    """RunnableConfig 里的旧 llm_model 不生效，以 state 里的选择为准。"""
    state = _make_state()
    config = {"configurable": {"llm_model": "deepseek-v4-flash"}}
    llm = _build_llm("key", state, config)
    assert llm.model_name == "deepseek-v4-pro"


def test_build_llm_falls_back_for_unsupported_state_model():
    """旧检查点里不受支持的模型名回退到默认模型。"""
    state = _make_state()
    state["model"] = "deepseek-chat"
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


def test_call_llm_passes_selected_model_and_tools_to_api(tmp_path):
    """验证请求参数：state 选定的模型、messages 转为 OpenAI 格式、附带 tools。"""
    state = _make_state(api_key="test-key")
    state["project_path"] = str(tmp_path)
    state["messages"] = [AIMessage(content="之前")]
    mock_openai, client = _patch_openai_stream([_chunk(content="好")])
    try:
        with patch("app.agent.nodes._publish_thinking"):
            call_llm(state, {"configurable": {"llm_model": "deepseek-v4-flash"}})
    finally:
        mock_openai.stop()

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-pro"
    assert kwargs["stream"] is True
    assert kwargs["parallel_tool_calls"] is False
    assert kwargs["messages"][0]["role"] == "system"
    assert "OneRad Research Agent" in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1] == {"role": "assistant", "content": "之前"}
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


def test_human_review_other_passes_instruction():
    """resume {"action": "other", "instruction": ...} 时按取消处理并传递指令。"""
    state = _make_state()
    state.update({
        "interrupt_type": "system_command",
        "pending_command": {"tool_call_id": "tc1", "command": "ls"},
    })

    with patch(
        "app.agent.nodes.interrupt",
        return_value={"action": "other", "instruction": "改成只列出 txt 文件"},
    ):
        updates = human_review(state)

    assert updates["confirmed"] is False
    assert updates["other_instruction"] == "改成只列出 txt 文件"


def test_human_review_confirm_clears_other_instruction():
    """非 other 动作不应携带替代指令。"""
    state = _make_state()
    state.update({
        "interrupt_type": "system_command",
        "pending_command": {"tool_call_id": "tc1", "command": "ls"},
    })

    with patch("app.agent.nodes.interrupt", return_value={"action": "cancel"}):
        updates = human_review(state)

    assert updates["confirmed"] is False
    assert updates["other_instruction"] is None


def test_execute_confirmed_marks_executed_results():
    """执行完成后的 ToolMessage 必须显式标记 executed，
    否则 LLM 会把执行结果误读为"计划已生成"而再次要求用户确认。"""
    state = _make_state()
    state.update({
        "interrupt_type": "file_plan",
        "confirmed": True,
        "pending_plan": {
            "tool_call_id": "tc1",
            "plan": [{"action": "rename", "source": "a", "target": "b", "reason": "r"}],
        },
    })

    with patch(
        "app.agent.nodes.execute_plan",
        return_value=[{"success": True, "action": "rename", "target": "b"}],
    ):
        result = execute_confirmed(state)

    content = json.loads(result["messages"][0].content)
    assert content["executed"] is True
    assert content["results"] == [{"success": True, "action": "rename", "target": "b"}]


def test_execute_confirmed_other_cancels_and_appends_instruction():
    """other 走取消路径：补取消 ToolMessage、追加 HumanMessage、清空中断状态。"""
    state = _make_state()
    state.update({
        "interrupt_type": "system_command",
        "confirmed": False,
        "other_instruction": "改成只列出 txt 文件",
        "pending_command": {"tool_call_id": "tc1", "command": "ls"},
    })

    result = execute_confirmed(state)

    msgs = result["messages"]
    assert len(msgs) == 2
    assert isinstance(msgs[0], ToolMessage)
    assert msgs[0].tool_call_id == "tc1"
    content = json.loads(msgs[0].content)
    assert content["cancelled"] is True
    assert content["reason"] == "用户取消了操作并提供了替代指令"
    assert isinstance(msgs[1], HumanMessage)
    assert msgs[1].content == "改成只列出 txt 文件"

    assert result["interrupt_type"] is None
    assert result["pending_command"] is None
    assert result["confirmed"] is None
    assert result["other_instruction"] is None


def test_execute_confirmed_cancel_without_instruction_keeps_plain_reason():
    """普通取消（无替代指令）保持原有 reason，且不追加 HumanMessage。"""
    state = _make_state()
    state.update({
        "interrupt_type": "system_command",
        "confirmed": False,
        "other_instruction": None,
        "pending_command": {"tool_call_id": "tc1", "command": "ls"},
    })

    result = execute_confirmed(state)

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], ToolMessage)
    content = json.loads(msgs[0].content)
    assert content["cancelled"] is True
    assert content["reason"] == "用户取消了操作"



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


def test_publish_agent_progress_publishes_payload():
    """正常提取中：进度载荷经 bridge 发布。"""
    import asyncio
    from unittest.mock import AsyncMock
    from app.agent import runtime as agent_runtime
    from app.agent.nodes import _publish_agent_progress

    loop = asyncio.new_event_loop()
    bridge = MagicMock()
    bridge.publish = AsyncMock()
    agent_runtime.register("t-prog", loop=loop, bridge=bridge)
    try:
        _publish_agent_progress(
            "t-prog", {"stage": "extracting", "current": 1, "total": 3}
        )
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        agent_runtime.unregister("t-prog")
        loop.close()

    bridge.publish.assert_awaited_once_with(
        "agent",
        "t-prog",
        {
            "radiomics_progress": {"stage": "extracting", "current": 1, "total": 3},
            "running": True,
        },
    )


def test_publish_agent_progress_suppressed_after_cancel():
    """/stop 置位 cancel_event 后不再推送进度：提取线程在当前病例收尾期间
    继续推送 running:True 会把前端 busy 重新置回运行中，看起来"后台还在跑"。"""
    import asyncio
    from unittest.mock import AsyncMock
    from app.agent import runtime as agent_runtime
    from app.agent.nodes import _publish_agent_progress

    loop = asyncio.new_event_loop()
    bridge = MagicMock()
    bridge.publish = AsyncMock()
    ctx = agent_runtime.register("t-prog-cancel", loop=loop, bridge=bridge)
    ctx.cancel_event.set()
    try:
        _publish_agent_progress(
            "t-prog-cancel", {"stage": "extracting", "current": 2, "total": 3}
        )
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        agent_runtime.unregister("t-prog-cancel")
        loop.close()

    bridge.publish.assert_not_called()


# ---------- read_yaml / update_yaml ----------

def _write_yaml(tmp_path, text):
    p = tmp_path / "params.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_read_yaml_full(tmp_path):
    _write_yaml(tmp_path, "setting:\n  binWidth: 25\n  normalize: false\n")
    res = _run_system_command(
        {"_pending_tool": "read_yaml", "args": {"path": "params.yaml"}},
        str(tmp_path),
    )
    assert res["tool"] == "read_yaml"
    assert res["result"] == {"setting": {"binWidth": 25, "normalize": False}}


def test_read_yaml_key_path(tmp_path):
    _write_yaml(tmp_path, "setting:\n  binWidth: 25\n")
    res = _run_system_command(
        {"_pending_tool": "read_yaml",
         "args": {"path": "params.yaml", "key": "setting.binWidth"}},
        str(tmp_path),
    )
    assert res["result"] == 25


def test_read_yaml_missing_key_returns_error(tmp_path):
    _write_yaml(tmp_path, "setting:\n  binWidth: 25\n")
    res = _run_system_command(
        {"_pending_tool": "read_yaml",
         "args": {"path": "params.yaml", "key": "setting.nope"}},
        str(tmp_path),
    )
    assert "键不存在" in res["error"]


def test_update_yaml_preserves_comments(tmp_path):
    _write_yaml(
        tmp_path,
        "# 顶部注释\nsetting:\n  binWidth: 25  # 行内注释\n  label: 1\n",
    )
    res = _run_system_command(
        {"_pending_tool": "update_yaml",
         "args": {"path": "params.yaml",
                  "updates": {"setting.binWidth": 10,
                              "setting.resampledPixelSpacing": [1.0, 1.0, 2.0],
                              "newSection.key": "v"}}},
        str(tmp_path),
    )
    assert res["tool"] == "update_yaml"
    assert set(res["result"]["updated"]) == {
        "setting.binWidth", "setting.resampledPixelSpacing", "newSection.key"}

    text = (tmp_path / "params.yaml").read_text(encoding="utf-8")
    assert "# 顶部注释" in text
    assert "# 行内注释" in text

    import yaml
    data = yaml.safe_load(text)
    assert data["setting"]["binWidth"] == 10
    assert data["setting"]["label"] == 1  # 未提及的键保持原值
    assert data["setting"]["resampledPixelSpacing"] == [1.0, 1.0, 2.0]
    assert data["newSection"] == {"key": "v"}


def test_update_yaml_invalid_args(tmp_path):
    _write_yaml(tmp_path, "a: 1\n")
    res = _run_system_command(
        {"_pending_tool": "update_yaml",
         "args": {"path": "params.yaml", "updates": {}}},
        str(tmp_path),
    )
    assert "updates" in res["error"]


def test_yaml_tools_reject_sandbox_escape(tmp_path):
    for t in ("read_yaml", "update_yaml"):
        args = {"path": "../outside.yaml"}
        if t == "update_yaml":
            args["updates"] = {"a": 1}
        res = _run_system_command({"_pending_tool": t, "args": args}, str(tmp_path))
        assert "error" in res
