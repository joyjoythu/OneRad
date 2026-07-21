import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from app.agent import build_initial_state, create_agent_graph
from app.agent.nodes import (
    EXPLORE_SUBAGENT_SYSTEM_PROMPT,
    SUBAGENT_SYSTEM_PROMPT,
    _summarize_subagent_entries,
)
from app.agent.tools import build_tools
from app.api.agent import _sync_payload


def _make_state(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-v4-pro"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="帮我看看项目里有什么")]
    return state


def _dispatch_call(tasks=None):
    if tasks is None:
        tasks = ["统计项目根目录下的文件数量"]
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "dispatch_subagent",
            "args": {"tasks": tasks},
            "id": "call_sub",
        }],
    )


def _explore_dispatch_call(tasks=None):
    if tasks is None:
        tasks = ["统计项目根目录下的文件数量"]
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "dispatch_subagent",
            "args": {"tasks": tasks, "mode": "explore"},
            "id": "call_explore",
        }],
    )


def _find_tool_message(messages, tool_call_id):
    for m in messages:
        if isinstance(m, ToolMessage) and m.tool_call_id == tool_call_id:
            return m
    return None


def test_dispatch_subagent_runs_nested_graph(tmp_path):
    """端到端（嵌套 invoke spike 验证）：主 agent 分派 → 审批确认 →
    子 agent 在隔离上下文中自主运行 → 结论作为工具结果回到主对话。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {
        "configurable": {"thread_id": "test-subagent", "api_key": "fake"}
    }

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            _dispatch_call(),
            AIMessage(content="子任务结论：项目里共有 3 个文件"),
            AIMessage(content="主 agent 总结"),
        ]

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        snapshot = graph.get_state(config)
        assert snapshot.values["interrupt_type"] == "subagent_dispatch"
        assert snapshot.values["pending_subagent"]["tasks"] == ["统计项目根目录下的文件数量"]

        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    # 主 agent 首次调用 → 子 agent 一次调用 → 主 agent 收尾，共 3 次 LLM 调用
    assert mock_stream.call_count == 3

    # 子 agent 的调用特征：以子任务系统提示开头，工具集中没有 dispatch_subagent（深度限 1 层）
    sub_call = mock_stream.call_args_list[1]
    sub_messages = sub_call.kwargs["messages"]
    assert any(
        isinstance(message, SystemMessage)
        and message.content == SUBAGENT_SYSTEM_PROMPT
        for message in sub_messages
    )
    sub_tool_names = {t.name for t in sub_call.kwargs["tools"]}
    assert "dispatch_subagent" not in sub_tool_names
    assert "list_directory" in sub_tool_names

    # 结论经 ToolMessage 回到主对话，主 agent 继续完成回复
    tool_msg = _find_tool_message(final["messages"], "call_sub")
    assert tool_msg is not None
    assert "\\u5b50" not in tool_msg.content
    assert "子任务结论" in tool_msg.content
    parsed = json.loads(tool_msg.content)
    assert parsed["success"] is True
    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["success"] is True
    assert "子任务结论" in parsed["results"][0]["result"]
    assert parsed["results"][0]["task"] == "统计项目根目录下的文件数量"
    assert final["messages"][-1].content == "主 agent 总结"
    # 中断状态已清理
    assert final["interrupt_type"] is None
    assert final["pending_subagent"] is None


def test_dispatch_subagent_inner_tools_auto_approved(tmp_path):
    """子 agent 内部的工具调用自动批准（不触发 interrupt）。"""
    (tmp_path / "a.txt").write_text("x")
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {
        "configurable": {"thread_id": "test-subagent-auto", "api_key": "fake"}
    }

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            _dispatch_call(),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "list_directory",
                    "args": {"path": "."},
                    "id": "sub_call_list",
                }],
            ),
            AIMessage(content="子任务结论：目录里有 a.txt"),
            AIMessage(content="主 agent 总结"),
        ]

        list(graph.stream(state, config))
        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    assert mock_stream.call_count == 4
    # 子 agent 的 list_directory 真实执行（结果出现在子上下文，但结论回到主对话）
    tool_msg = _find_tool_message(final["messages"], "call_sub")
    parsed = json.loads(tool_msg.content)
    assert parsed["success"] is True
    assert "a.txt" in parsed["results"][0]["result"]


def test_dispatch_subagent_cancel_skips_run(tmp_path):
    """取消分派：子 agent 不运行，返回取消标记。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {
        "configurable": {"thread_id": "test-subagent-cancel", "api_key": "fake"}
    }

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            _dispatch_call(),
            AIMessage(content="好的，不分派了"),
        ]

        list(graph.stream(state, config))
        final = graph.invoke(Command(resume={"action": "cancel"}), config)

    # 子 agent 未运行：只有主 agent 的两次调用
    assert mock_stream.call_count == 2
    tool_msg = _find_tool_message(final["messages"], "call_sub")
    parsed = json.loads(tool_msg.content)
    assert parsed["cancelled"] is True


def test_dispatch_subagent_failure_returns_error(tmp_path):
    """子 agent 运行异常：错误作为工具结果返回，主 agent 继续。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {
        "configurable": {"thread_id": "test-subagent-fail", "api_key": "fake"}
    }

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            _dispatch_call(),
            RuntimeError("boom"),
            AIMessage(content="子任务失败了，换个方式"),
        ]

        list(graph.stream(state, config))
        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    tool_msg = _find_tool_message(final["messages"], "call_sub")
    parsed = json.loads(tool_msg.content)
    assert parsed["success"] is False
    assert parsed["results"][0]["success"] is False
    assert "boom" in parsed["results"][0]["error"]
    assert final["messages"][-1].content == "子任务失败了，换个方式"


def test_build_tools_subagent_flag_controls_dispatch_tool(tmp_path):
    llm = MagicMock()
    with_dispatch = build_tools(str(tmp_path), llm, allow_subagent=True)
    without_dispatch = build_tools(str(tmp_path), llm, allow_subagent=False)
    assert "dispatch_subagent" in with_dispatch
    assert "dispatch_subagent" not in without_dispatch


def test_summarize_subagent_entries():
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="task"),
        AIMessage(
            content="",
            tool_calls=[{"name": "list_directory", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content='{"result": "a.txt"}', tool_call_id="c1"),
        AIMessage(content="找到了一个文件"),
    ]
    entries = _summarize_subagent_entries(messages)
    assert {"role": "assistant", "text": "调用工具：list_directory"} in entries
    assert any(e["role"] == "tool" and "a.txt" in e["text"] for e in entries)
    assert entries[-1] == {"role": "assistant", "text": "找到了一个文件"}


def test_sync_payload_includes_pending_subagent():
    payload = _sync_payload(
        {"pending_subagent": {"tool_call_id": "c1", "tasks": ["做件事"]}},
        running=False,
    )
    assert payload["pending_subagent"] == {"tool_call_id": "c1", "tasks": ["做件事"]}


def test_dispatch_multiple_subagents_in_parallel(tmp_path):
    """一次分派多个子任务：并行运行，结果按任务逐个汇总。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-subagent-parallel", "api_key": "fake"}}

    def route_response(*args, **kwargs):
        messages = kwargs["messages"]
        for m in messages:
            if isinstance(m, SystemMessage) and m.content == SUBAGENT_SYSTEM_PROMPT:
                # 子 agent：根据任务内容给出不同结论
                task_text = next(
                    x.content for x in messages if isinstance(x, HumanMessage)
                )
                return AIMessage(content=f"结论：{task_text} 已完成")
        return AIMessage(content="主 agent 总结")

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        first_call = {"done": False}

        def first_then_route(*args, **kwargs):
            if not first_call["done"]:
                first_call["done"] = True
                return _dispatch_call(tasks=["统计数据文件", "检查掩膜目录"])
            return route_response(*args, **kwargs)

        mock_stream.side_effect = first_then_route

        events = list(graph.stream(state, config))
        assert any("__interrupt__" in e for e in events)

        snapshot = graph.get_state(config)
        assert snapshot.values["pending_subagent"]["tasks"] == ["统计数据文件", "检查掩膜目录"]

        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    tool_msg = _find_tool_message(final["messages"], "call_sub")
    parsed = json.loads(tool_msg.content)
    assert parsed["success"] is True
    assert len(parsed["results"]) == 2
    by_task = {r["task"]: r for r in parsed["results"]}
    assert "统计数据文件 已完成" in by_task["统计数据文件"]["result"]
    assert "检查掩膜目录 已完成" in by_task["检查掩膜目录"]["result"]
    assert final["messages"][-1].content == "主 agent 总结"
    # 主 agent 2 次（分派 + 收尾）+ 每个子任务各 1 次
    assert mock_stream.call_count == 4


def test_dispatch_subagent_object_form_tasks_normalized(tmp_path):
    """模型常把 tasks 写成对象数组（{"task": ..., "task_id": ...}）：
    应归一化为字符串任务列表并照常进入审批，而不是参数校验崩掉整张图。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-subagent-objargs", "api_key": "fake"}}

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.return_value = AIMessage(
            content="",
            tool_calls=[{
                "name": "dispatch_subagent",
                "args": {"tasks": [
                    {"task": "统计数据文件", "task_id": "a"},
                    "检查掩膜目录",
                ]},
                "id": "call_sub",
            }],
        )
        events = list(graph.stream(state, config))

    assert any("__interrupt__" in e for e in events)
    snapshot = graph.get_state(config)
    assert snapshot.values["pending_subagent"]["tasks"] == ["统计数据文件", "检查掩膜目录"]


def test_dispatch_subagent_invalid_args_does_not_crash_graph(tmp_path):
    """工具参数完全无法解析时（如 tasks 不是数组）：回复错误 ToolMessage
    让模型重试，而不是让图在 process_tool_calls 崩溃——崩溃会把没有
    ToolMessage 的 tool_calls 留在历史里，之后每轮 LLM 调用都会 400。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-subagent-badargs", "api_key": "fake"}}

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        first = {"done": False}

        def side_effect(*args, **kwargs):
            if not first["done"]:
                first["done"] = True
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "dispatch_subagent",
                        "args": {"tasks": 42},
                        "id": "call_sub",
                    }],
                )
            return AIMessage(content="好的，我换用正确的格式重新调用")

        mock_stream.side_effect = side_effect
        final = graph.invoke(state, config)

    tool_msg = _find_tool_message(final["messages"], "call_sub")
    assert tool_msg is not None
    assert "error" in json.loads(tool_msg.content)
    assert final["messages"][-1].content == "好的，我换用正确的格式重新调用"


def test_dispatch_subagent_under_async_parent_with_sqlite_saver(tmp_path):
    """生产路径复现：父图经 astream + AsyncSqliteSaver 运行、execute_confirmed
    在事件循环的执行器线程中跑子 agent 的同步 stream。"""
    import asyncio

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.agent import runtime as agent_runtime

    async def main():
        state = _make_state(tmp_path)
        published = []

        class FakeBridge:
            async def publish(self, event, thread_id, payload, persist=True):
                published.append(payload)

        async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:
            graph = create_agent_graph(saver)
            config = {
                "configurable": {"thread_id": "parent-thread", "api_key": "fake"}
            }
            agent_runtime.register(
                "parent-thread", loop=asyncio.get_running_loop(), bridge=FakeBridge()
            )
            try:
                with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
                    mock_stream.side_effect = [
                        _dispatch_call(),
                        AIMessage(content="子任务结论：共 3 个文件"),
                        AIMessage(content="主 agent 总结"),
                    ]
                    async for _ in graph.astream(state, config, stream_mode="values"):
                        pass
                    final = None
                    async for values in graph.astream(
                        Command(resume={"action": "confirm"}), config, stream_mode="values"
                    ):
                        final = values
            finally:
                agent_runtime.unregister("parent-thread")

        assert final is not None
        tool_msg = _find_tool_message(final["messages"], "call_sub")
        assert tool_msg is not None, (
            f"缺少 dispatch 的 ToolMessage：{[type(m).__name__ for m in final['messages']]}"
        )
        parsed = json.loads(tool_msg.content)
        assert parsed.get("success") is True, f"子 agent 失败: {parsed}"
        assert "子任务结论" in parsed["results"][0]["result"]
        # 子 agent 状态事件应推送到父线程的 bridge
        subagent_events = [p for p in published if "subagent" in p]
        assert subagent_events, "未收到任何 subagent 状态推送"
        assert subagent_events[-1]["subagent"]["status"] == "done"
        assert subagent_events[-1]["subagent"]["id"]

    asyncio.run(main())


def test_dispatch_subagent_recursion_limit_returns_partial(tmp_path, monkeypatch):
    """子 agent 在单次 stream 内完成全部生命周期，每个工具轮次消耗 4 个
    superstep（call_llm→process→auto_confirm→execute_confirmed），
    recursion_limit 太小会导致探索型任务提前触顶。
    触顶时应返回已完成探索的部分结论，而不是整体失败。"""
    monkeypatch.setattr("app.agent.nodes._SUBAGENT_RECURSION_LIMIT", 5)
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {
        "configurable": {"thread_id": "test-subagent-limit", "api_key": "fake"}
    }

    counter = {"n": 0, "dispatched": False}

    def route_response(*args, **kwargs):
        messages = kwargs["messages"]
        if any(
            isinstance(m, SystemMessage) and m.content == SUBAGENT_SYSTEM_PROMPT
            for m in messages
        ):
            # 子 agent 每轮都带内容地调用工具（模拟长时间探索）→ 必然触顶
            counter["n"] += 1
            return AIMessage(
                content=f"探索进展 {counter['n']}",
                tool_calls=[{
                    "name": "list_directory",
                    "args": {"path": "."},
                    "id": f"sub_loop_{counter['n']}",
                }],
            )
        if not counter["dispatched"]:
            counter["dispatched"] = True
            return _dispatch_call()
        return AIMessage(content="主 agent 总结")

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = route_response

        list(graph.stream(state, config))
        final = graph.invoke(Command(resume={"action": "confirm"}), config)

    tool_msg = _find_tool_message(final["messages"], "call_sub")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    result = parsed["results"][0]
    assert result.get("partial") is True, f"触顶时应返回部分结论: {parsed}"
    assert result["success"] is True
    assert "探索进展" in result["result"]
    assert "步数上限" in result["note"]
    assert final["messages"][-1].content == "主 agent 总结"


def test_build_tools_readonly_flag_limits_toolset(tmp_path):
    """readonly=True 时只注册只读探索工具：目录/文件探查 + YAML/JSON/表格读取 + 配对扫描
    + spacing 检测，不含脚本执行、文件操作计划、YAML 修改、特征提取、分析等写/重操作。"""
    llm = MagicMock()
    tools = build_tools(str(tmp_path), llm, readonly=True)
    assert set(tools) == {
        "list_directory",
        "find_files",
        "get_file_info",
        "read_yaml",
        "read_json",
        "read_tabular_file",
        "discover_radiomics_pairs",
        "inspect_image_spacing",
    }


def test_dispatch_explore_mode_skips_confirmation(tmp_path):
    """mode="explore" 的派发免确认：不产生 interrupt，子 agent 立即执行，
    结果作为 ToolMessage 回到主对话，主 agent 继续收尾。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-explore-skip", "api_key": "fake"}}

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            _explore_dispatch_call(),
            AIMessage(content="探索结论：项目里共有 3 个文件"),
            AIMessage(content="主 agent 总结"),
        ]
        final = graph.invoke(state, config)

    # 主 agent 分派 → 子 agent 一次调用 → 主 agent 收尾，全程无确认中断
    assert mock_stream.call_count == 3
    assert final["interrupt_type"] is None
    assert final.get("pending_subagent") is None
    tool_msg = _find_tool_message(final["messages"], "call_explore")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed["success"] is True
    assert "探索结论" in parsed["results"][0]["result"]
    assert final["messages"][-1].content == "主 agent 总结"


def test_explore_subagent_uses_readonly_toolset(tmp_path):
    """explore 模式的子 agent 使用探索专用 system prompt，且工具集为只读。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-explore-readonly", "api_key": "fake"}}

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            _explore_dispatch_call(),
            AIMessage(content="探索结论"),
            AIMessage(content="主 agent 总结"),
        ]
        graph.invoke(state, config)

    sub_call = mock_stream.call_args_list[1]
    sub_messages = sub_call.kwargs["messages"]
    assert any(
        isinstance(message, SystemMessage)
        and message.content == EXPLORE_SUBAGENT_SYSTEM_PROMPT
        for message in sub_messages
    )
    sub_tool_names = {t.name for t in sub_call.kwargs["tools"]}
    assert sub_tool_names == {
        "list_directory",
        "find_files",
        "get_file_info",
        "read_yaml",
        "read_json",
        "read_tabular_file",
        "discover_radiomics_pairs",
        "inspect_image_spacing",
    }


def test_dispatch_explore_mode_parallel_tasks(tmp_path):
    """explore 模式一次派发多个只读子任务：免确认并行执行，结果逐个汇总。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-explore-parallel", "api_key": "fake"}}

    def route_response(*args, **kwargs):
        messages = kwargs["messages"]
        for m in messages:
            if isinstance(m, SystemMessage) and m.content == EXPLORE_SUBAGENT_SYSTEM_PROMPT:
                task_text = next(
                    x.content for x in messages if isinstance(x, HumanMessage)
                )
                return AIMessage(content=f"结论：{task_text} 已完成")
        return AIMessage(content="主 agent 总结")

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        first_call = {"done": False}

        def first_then_route(*args, **kwargs):
            if not first_call["done"]:
                first_call["done"] = True
                return _explore_dispatch_call(tasks=["统计数据文件", "检查掩膜目录"])
            return route_response(*args, **kwargs)

        mock_stream.side_effect = first_then_route
        final = graph.invoke(state, config)

    tool_msg = _find_tool_message(final["messages"], "call_explore")
    parsed = json.loads(tool_msg.content)
    assert parsed["success"] is True
    assert len(parsed["results"]) == 2
    by_task = {r["task"]: r for r in parsed["results"]}
    assert "统计数据文件 已完成" in by_task["统计数据文件"]["result"]
    assert "检查掩膜目录 已完成" in by_task["检查掩膜目录"]["result"]
    assert final["messages"][-1].content == "主 agent 总结"
    # 主 agent 2 次（分派 + 收尾）+ 每个子任务各 1 次，全程无确认
    assert mock_stream.call_count == 4
    assert final["interrupt_type"] is None


def test_dispatch_unknown_mode_falls_back_to_general(tmp_path):
    """未知 mode 一律按 general 处理：仍需用户确认后才执行子 agent。"""
    state = _make_state(tmp_path)
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-explore-fallback", "api_key": "fake"}}

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.return_value = AIMessage(
            content="",
            tool_calls=[{
                "name": "dispatch_subagent",
                "args": {"tasks": ["做件事"], "mode": "turbo"},
                "id": "call_sub",
            }],
        )
        events = list(graph.stream(state, config))

    assert any("__interrupt__" in e for e in events)
    snapshot = graph.get_state(config)
    assert snapshot.values["interrupt_type"] == "subagent_dispatch"
    assert snapshot.values["pending_subagent"]["tasks"] == ["做件事"]
