# Agent 界面实时显示模型思考链 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在 Agent 聊天界面实时看到推理模型（deepseek-v4-flash）的思考链，流式展开；完成后思考链以可折叠区块保留在对应 assistant 消息气泡内，刷新后可回看。

**Architecture:** `call_llm` 从 LangChain `.invoke()` 改为 openai SDK `stream=True` 直调 DeepSeek，流式循环中把 `reasoning_content` 累积全文经旁路事件（仿 `_publish_agent_progress`，`persist=False` 不落库）推给前端 Pinia store 的独立 `currentThinking` ref；流结束后完整思考链挂在 `AIMessage.additional_kwargs["reasoning_content"]` 上走现有 values 快照通路，`_render_messages` 透传给历史消息。前端流式期间在消息列表末尾显示滚动思考气泡，历史消息气泡内渲染可折叠"思考过程"区块。

**Tech Stack:** FastAPI + SSE（EventBridge）、LangGraph、openai SDK（已是依赖）、Vue 3 + Pinia + Element Plus、pytest、vitest。

**设计依据:** `docs/superpowers/specs/2026-07-18-agent-thinking-stream-design.md`

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `app/api/sse.py` | EventBridge.publish 增加 `persist` 开关 | 修改 |
| `app/agent/nodes.py` | `call_llm` 流式改造、`_stream_chat_completion`、`_publish_thinking`、`_resolve_model` | 修改 |
| `app/api/agent.py` | `_render_messages` 透传 `reasoning_content` | 修改 |
| `frontend/src/api/agent.ts` | `ThinkingState` 类型、`AgentMessage.reasoning_content`、`AgentState.thinking` | 修改 |
| `frontend/src/stores/agent.ts` | `currentThinking` ref 及合并/清空逻辑 | 修改 |
| `frontend/src/components/AgentChat.vue` | 流式思考气泡 + 历史消息可折叠思考区块 | 修改 |
| `tests/test_sse_bridge.py` | persist=False 测试 | 修改 |
| `tests/test_agent_nodes.py` | 流式 call_llm 新测试；重写 2 个旧 call_llm 测试 | 修改 |
| `tests/test_agent_graph.py` | 迁移 9 处 ChatOpenAI mock 到新 seam | 修改 |
| `tests/test_api_agent.py` | 迁移 1 处 mock；新增 `_render_messages` 透传测试 | 修改 |
| `frontend/src/stores/__tests__/agent.spec.ts` | currentThinking 合并/清空测试 | 修改 |
| `frontend/src/components/__tests__/AgentChat.spec.ts` | 思考气泡/折叠区块渲染测试 | 修改 |

**不受影响的测试**（只经过 `process_tool_calls`/`execute_confirmed`，不经过 `call_llm`，无需改动）：
`tests/test_radiomics_nodes.py`、`tests/test_radiomics_integration.py`、`tests/test_radiomics_analysis_nodes.py`、`tests/test_agent_graph.py::test_process_tool_calls_unknown_tool_returns_error`。

---

### Task 1: EventBridge.publish 增加 persist 开关

thinking 流式事件频率高（每个 delta 一条），全部落库会撑大 `sse_events` 表。给 `publish` 加 `persist=False` 选项：只投递给在线订阅者，不写 SQLite、不参与回放。事件 id 照常分配（烧掉 id 留空洞是安全的，回放只比较 `event_id > last_event_id`，见 `sse.py:17-22` 注释）。

**Files:**
- Modify: `app/api/sse.py:78-104`
- Test: `tests/test_sse_bridge.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_sse_bridge.py` 末尾追加：

```python
@pytest.mark.anyio
async def test_publish_without_persist_delivers_but_skips_store(bridge):
    """persist=False 的事件投递给订阅者但不落库、不回放。"""
    queue = await bridge.subscribe("run", "run-1")

    event_id = await bridge.publish(
        "run", "run-1", {"thinking": {"text": "想", "done": False}}, persist=False
    )

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received["event_id"] == event_id
    assert received["data"] == {"thinking": {"text": "想", "done": False}}

    # 不落库：新订阅者从头回放时拿不到该事件
    replay = await bridge.subscribe("run", "run-1", last_event_id=0)
    assert replay.empty()

    # id 照常单调递增：后续持久化事件 id 更大（空洞安全）
    next_id = await bridge.publish("run", "run-1", {"message": "after"})
    assert next_id > event_id
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sse_bridge.py::test_publish_without_persist_delivers_but_skips_store -v`
Expected: FAIL — `TypeError: EventBridge.publish() got an unexpected keyword argument 'persist'`

- [ ] **Step 3: 实现 persist 开关**

修改 `app/api/sse.py` 的 `publish` 方法（78-104 行），改为：

```python
    async def publish(
        self, scope: str, scope_id: str, data: Any, *, persist: bool = True
    ) -> int:
        payload = json.dumps(data, ensure_ascii=False)
        lock = self._scope_lock(scope, scope_id)
        key = self._key(scope, scope_id)

        async with lock:
            event_id = await self._allocate_event_id(key, scope, scope_id)
            if persist:
                write_task = asyncio.ensure_future(
                    run_in_threadpool(
                        self.store.record_sse_event, scope, scope_id, event_id, payload
                    )
                )
                self._track_write(key, write_task)
                # shield 阻止发布者被取消时取消传播进写任务：写任务只在 store
                # 写入真正落库后才完成。若发布者在等待期间被取消，写入仍会落库
                # （回放/重连可获取；流结束时前端还会同步最终状态），仅本次
                # 不再向订阅队列投递。
                await asyncio.shield(write_task)
            for queue in self._queues.get(key, {}).values():
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await queue.put({"event_id": event_id, "data": data})

        return event_id
```

注意：`payload` 变量在 `persist=False` 分支未使用，保留无妨（与现有风格一致）；不要删除。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sse_bridge.py -v`
Expected: 全部 PASS（含旧测试——默认 `persist=True` 行为不变）

- [ ] **Step 5: Commit**

```bash
git add app/api/sse.py tests/test_sse_bridge.py
git commit -m "feat(sse): add persist=False option to EventBridge.publish for high-frequency events"
```

---

### Task 2: call_llm 流式改造（核心）

`call_llm` 目前用 `ChatOpenAI.bind_tools().invoke()` 非流式调用，`reasoning_content` 被 LangChain 丢弃。改为：openai SDK `stream=True` 直调，流式循环中累积 reasoning/content/tool_calls 三类 delta，reasoning 累积全文经 `_publish_thinking` 旁路推送；结束后组装 `AIMessage`（思考链放 `additional_kwargs["reasoning_content"]`），返回值契约不变。

关键 seam 设计：`_stream_chat_completion(api_key, base_url, model, messages, tools, thread_id)` 独立成函数——图级测试（Task 3）patch 它来注入 AIMessage，单测 patch `OpenAI` 类验证流式解析。

**Files:**
- Modify: `app/agent/nodes.py:1-79`（imports、`_build_llm`、`call_llm`），301-318 后新增 `_publish_thinking`
- Test: `tests/test_agent_nodes.py`

- [ ] **Step 1: 写失败测试（新增流式测试 + 重写 2 个旧 call_llm 测试）**

在 `tests/test_agent_nodes.py` 顶部更新 import：

```python
import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.agent.nodes import _build_llm, _resolve_api_key, auto_confirm, call_llm, route_after_process
from app.agent.state import AgentState
```

在 `_make_state` 之后新增 chunk 构造辅助函数：

```python
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
    mock_cls.return_value = client
    return mock_openai, client
```

然后**替换**现有的 `test_call_llm_records_context_usage` 和 `test_call_llm_omits_context_usage_when_api_returns_none` 两个测试（99-133 行），并新增推理链/tool_calls/错误测试，共 5 个：

```python
def test_call_llm_streams_reasoning_and_publishes_thinking(tmp_path):
    """reasoning_content delta 累积进 additional_kwargs，并逐次推送 thinking 事件。"""
    state = _make_state()
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
    state = _make_state()
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
    state = _make_state()
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


def test_call_llm_raises_on_invalid_tool_arguments(tmp_path):
    """tool_calls 参数 JSON 解析失败必须抛错，不得带错参数执行工具。"""
    state = _make_state()
    state["project_path"] = str(tmp_path)
    chunks = [_chunk(tool_calls=[_tc_delta(0, id="call_1", name="list_directory", arguments="{oops")])]
    mock_openai, _ = _patch_openai_stream(chunks)
    try:
        with patch("app.agent.nodes._publish_thinking"):
            with pytest.raises(ValueError, match="list_directory"):
                call_llm(state)
    finally:
        mock_openai.stop()


def test_call_llm_passes_model_and_tools_to_api(tmp_path):
    """验证请求参数：模型名来自 config、messages 转为 OpenAI 格式、附带 tools。"""
    state = _make_state()
    state["project_path"] = str(tmp_path)
    state["messages"] = [AIMessage(content="之前")]
    mock_openai, client = _patch_openai_stream([_chunk(content="好")])
    try:
        with patch("app.agent.nodes._publish_thinking"):
            call_llm(state, {"configurable": {"llm_model": "deepseek-v4-flash"}})
    finally:
        mock_openai.stop()

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-flash"
    assert kwargs["stream"] is True
    assert kwargs["parallel_tool_calls"] is False
    assert kwargs["messages"] == [{"role": "assistant", "content": "之前"}]
    assert any(t["function"]["name"] == "list_directory" for t in kwargs["tools"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_nodes.py -v -k call_llm`
Expected: FAIL — `AttributeError: module 'app.agent.nodes' does not have 'OpenAI'`（或 `_publish_thinking` 不存在）

- [ ] **Step 3: 实现流式 call_llm**

修改 `app/agent/nodes.py`：

(a) 顶部 imports（1-20 行）改为：

```python
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import AIMessage, ToolMessage, convert_to_openai_messages
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from openai import OpenAI

from app.agent.state import AgentState
from app.agent.tools import build_tools
from app.agent.safety import Sandbox
from app.agent import runtime as agent_runtime
from app.actions import execute_plan
from app.code_runner import execute_script_if_safe
from app.feature import FeatureAgent
from app.radiomics_analysis import run_radiomics_cv_analysis
```

(b) `_build_llm`（25-37 行）重构：提取模型解析为 `_resolve_model`，`_build_llm` 复用它：

```python
def _resolve_model(state: AgentState, config: Optional[RunnableConfig] = None) -> str:
    """解析本次调用使用的模型名：config 覆盖优先于 state。"""
    model = state["model"]
    if config is not None:
        model = config.get("configurable", {}).get("llm_model") or model
    return model


def _build_llm(
    api_key: str, state: AgentState, config: Optional[RunnableConfig] = None
) -> ChatOpenAI:
    """根据状态构造 ChatOpenAI 实例（供工具内部调用，如 plan_file_operations）。"""
    return ChatOpenAI(
        api_key=api_key or None,
        base_url=state["base_url"],
        model=_resolve_model(state, config),
        temperature=0.2,
    )
```

(c) `call_llm`（68-79 行）替换为：

```python
def call_llm(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """流式调用 LLM，边收 reasoning_content 边推送 thinking 事件，组装 AIMessage。"""
    api_key = _resolve_api_key(state, config)
    llm = _build_llm(api_key, state, config)
    tools = build_tools(state["project_path"], llm)
    thread_id = (config or {}).get("configurable", {}).get("thread_id")
    response = _stream_chat_completion(
        api_key=api_key,
        base_url=state["base_url"],
        model=_resolve_model(state, config),
        messages=state["messages"],
        tools=list(tools.values()),
        thread_id=thread_id,
    )
    updates: dict = {"messages": [response]}
    usage = _extract_context_usage(response)
    if usage is not None:
        updates["context_usage"] = usage
    return updates


def _stream_chat_completion(
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Any],
    tools: List[Any],
    thread_id: Optional[str] = None,
) -> AIMessage:
    """openai SDK 流式调用 DeepSeek，返回组装好的 AIMessage。

    LangChain 的 ChatOpenAI 会丢弃 DeepSeek 的非标准 reasoning_content 字段，
    因此直接用 openai SDK：流式循环中累积 reasoning/content/tool_calls 三类
    delta，reasoning 累积全文经 _publish_thinking 旁路推送给前端；思考链最终
    挂在 AIMessage.additional_kwargs["reasoning_content"] 上随快照持久化。
    """
    client = OpenAI(api_key=api_key or None, base_url=base_url)
    stream = client.chat.completions.create(
        model=model,
        messages=convert_to_openai_messages(messages),
        tools=[convert_to_openai_tool(t) for t in tools],
        temperature=0.2,
        parallel_tool_calls=False,
        stream=True,
        stream_options={"include_usage": True},
    )

    reasoning_parts: List[str] = []
    content_parts: List[str] = []
    tool_slots: Dict[int, Dict[str, str]] = {}
    usage_metadata = None

    _publish_thinking(thread_id, "", False)
    for chunk in stream:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            usage_metadata = {
                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            }
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            reasoning_parts.append(reasoning)
            _publish_thinking(thread_id, "".join(reasoning_parts), False)
        if getattr(delta, "content", None):
            content_parts.append(delta.content)
        for tc in getattr(delta, "tool_calls", None) or []:
            slot = tool_slots.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                slot["id"] += tc.id
            function = getattr(tc, "function", None)
            if function is not None:
                if getattr(function, "name", None):
                    slot["name"] += function.name
                if getattr(function, "arguments", None):
                    slot["arguments"] += function.arguments

    full_reasoning = "".join(reasoning_parts)
    _publish_thinking(thread_id, full_reasoning, True)

    tool_calls = []
    for index in sorted(tool_slots):
        slot = tool_slots[index]
        try:
            args = json.loads(slot["arguments"]) if slot["arguments"] else {}
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"工具调用参数不是合法 JSON（{slot['name']}）: {slot['arguments']}"
            ) from exc
        tool_calls.append({
            "name": slot["name"],
            "args": args,
            "id": slot["id"] or f"call_{index}",
            "type": "tool_call",
        })

    additional_kwargs: Dict[str, Any] = {}
    if full_reasoning:
        additional_kwargs["reasoning_content"] = full_reasoning
    return AIMessage(
        content="".join(content_parts),
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
        usage_metadata=usage_metadata,
    )
```

(d) 在 `_publish_agent_progress`（301-318 行）之后新增 `_publish_thinking`：

```python
def _publish_thinking(thread_id: Optional[str], text: str, done: bool) -> None:
    """从节点线程向 SSE 订阅者推送模型思考链（reasoning_content）。

    与 _publish_agent_progress 同模式：节点在工作线程中运行，经
    run_coroutine_threadsafe 回到主事件循环发布。发送累积全文而非增量，
    丢事件/重连均自洽。persist=False 避免高频 delta 撑大 sse_events 表；
    重连后的兜底是 values 快照里 AIMessage 携带的完整思考链。
    """
    ctx = agent_runtime.get(thread_id)
    if ctx is None or ctx.loop is None or ctx.bridge is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            ctx.bridge.publish(
                "agent",
                thread_id,
                {"thinking": {"text": text, "done": done}, "running": True},
                persist=False,
            ),
            ctx.loop,
        )
    except Exception:
        logger.debug("推送思考内容失败", exc_info=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_nodes.py -v`
Expected: 全部 PASS（包括未改动的 `_build_llm`/`_resolve_api_key` 等旧测试）

- [ ] **Step 5: Commit**

```bash
git add app/agent/nodes.py tests/test_agent_nodes.py
git commit -m "feat(agent): stream DeepSeek reasoning_content in call_llm and publish thinking events"
```

---

### Task 3: 迁移图级测试的 LLM mock

`call_llm` 不再走 `ChatOpenAI.bind_tools().invoke()`，`tests/test_agent_graph.py` 中 9 处和 `tests/test_api_agent.py` 中 1 处 mock 会失效（表现为测试真实发起 HTTP 或 AttributeError）。迁移到新 seam `_stream_chat_completion`：图测试不关心流式细节，patch 它直接注入 AIMessage 序列。

**Files:**
- Modify: `tests/test_agent_graph.py`（9 处）
- Modify: `tests/test_api_agent.py:830-840`（1 处）

- [ ] **Step 1: 机械迁移简单站点（side_effect 列表型）**

适用于 `tests/test_agent_graph.py` 的 7 个测试：
`test_graph_runs_to_end_without_tools`（44 行）、`test_graph_interrupts_on_system_command`（62 行）、`test_graph_cancel_operation`（142 行）、`test_graph_interrupts_on_python_script`（220 行）、`test_graph_interrupts_on_low_risk_python_script`（263 行）、`test_graph_non_dict_resume_defaults_to_cancel`（303 行）、`test_graph_auto_approve_skips_interrupt`（362 行）。

替换模式——把：

```python
    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            AIMessage(...),
            AIMessage(content="Done"),
        ]
        mock_llm_class.return_value = mock_llm
```

改为：

```python
    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            AIMessage(...),
            AIMessage(content="Done"),
        ]
```

（AIMessage 内容保持原样逐字不变。）注意：
- `test_graph_runs_to_end_without_tools` 用的是 `invoke.return_value = AIMessage(content="Hi there")`，对应改为 `mock_stream.return_value = AIMessage(content="Hi there")`。
- `test_graph_interrupts_on_python_script` 的 `with` 还有第二个 patcher `patch("app.agent.nodes.execute_script_if_safe") as mock_execute`，保留它，只替换 ChatOpenAI 部分。

- [ ] **Step 2: 迁移两个 file_plan 测试（拆分型）**

`test_graph_interrupts_on_file_plan`（94-120 行）和 `test_graph_cancel_file_plan_does_not_execute`（173-197 行）的 side_effect 函数靠检查 SystemMessage 区分「工具内部规划调用」与「call_llm 调用」。拆分后更清晰：规划提示词仍走 ChatOpenAI mock（`plan_file_operations` 工具内部 `llm.invoke`，见 `app/agent/tools.py:52`），call_llm 走 `_stream_chat_completion` mock。

`test_graph_interrupts_on_file_plan` 的 with 块改为：

```python
    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class, \
         patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        # 工具内部规划调用（plan_file_operations 的规划 prompt 经 llm.invoke）。
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content='[{"action": "mkdir", "target": "new_folder", "reason": "create folder"}]'
        )
        mock_llm_class.return_value = mock_llm
        # call_llm 调用：第一次返回 plan 工具调用，第二次结束循环。
        mock_stream.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "plan_file_operations",
                    "args": {"instruction": "organize files"},
                    "id": "call_plan",
                }],
            ),
            AIMessage(content="Done"),
        ]
```

`test_graph_cancel_file_plan_does_not_execute` 的 with 块同样处理，规划返回内容用 `'[{"action": "mkdir", "target": "should_not_exist", "reason": "create folder"}]'`，`mock_stream.side_effect` 第一项的 tool_call id 为 `"call_cancel_plan"`。

- [ ] **Step 3: 迁移 test_api_agent.py 的 _run_interrupt_then_resume**

`tests/test_api_agent.py:830-840`，把：

```python
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
```

改为：

```python
    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{"name": "list_directory", "args": {"path": "."}, "id": "call_list"}],
            ),
            AIMessage(content="Done"),
        ]
```

- [ ] **Step 4: 运行受影响的测试文件确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_graph.py tests/test_api_agent.py tests/test_radiomics_nodes.py tests/test_radiomics_integration.py tests/test_radiomics_analysis_nodes.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_graph.py tests/test_api_agent.py
git commit -m "test(agent): migrate LLM mocks to _stream_chat_completion seam"
```

---

### Task 4: _render_messages 透传 reasoning_content

values 快照/历史接口经 `_render_messages` 把 AIMessage 转成 dict；目前只透传 timestamp，思考链会丢。透传 `reasoning_content` 让刷新/重连后历史消息仍携带思考链。

**Files:**
- Modify: `app/api/agent.py:159-163`
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_agent.py` 末尾追加（文件已有 AIMessage import，若无则加 `from langchain_core.messages import AIMessage`；`_render_messages` 从 `app.api.agent` import）：

```python
def test_render_messages_passes_through_reasoning_content():
    """assistant 消息的思考链透传到渲染结果，供历史消息展示。"""
    from app.api.agent import _render_messages

    ai = AIMessage(
        content="答案",
        additional_kwargs={"reasoning_content": "思考过程"},
    )
    rendered = _render_messages({"messages": [ai]})

    assert rendered[0]["role"] == "assistant"
    assert rendered[0]["reasoning_content"] == "思考过程"


def test_render_messages_omits_reasoning_when_absent():
    """无思考链的消息不应携带 reasoning_content 键。"""
    from app.api.agent import _render_messages

    ai = AIMessage(content="答案")
    rendered = _render_messages({"messages": [ai]})

    assert "reasoning_content" not in rendered[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_agent.py -v -k render_messages`
Expected: FAIL — `KeyError: 'reasoning_content'`

- [ ] **Step 3: 实现透传**

修改 `app/api/agent.py` 的 `_render_messages`（159-163 行），AIMessage 分支改为：

```python
        elif isinstance(msg, AIMessage):
            entry = {"role": "assistant", "content": _stringify_content(msg.content)}
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = tool_calls
            reasoning = msg.additional_kwargs.get("reasoning_content")
            if reasoning:
                entry["reasoning_content"] = reasoning
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_agent.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat(api): pass through reasoning_content in rendered agent messages"
```

---

### Task 5: 前端类型与 store 状态

新增 `ThinkingState` 类型与 `currentThinking` ref。流式文本**不写入 messages**（快照会整体替换 messages 冲掉本地拼接），走独立 ref；合并模式与 `radiomics_progress` 一致。

**Files:**
- Modify: `frontend/src/api/agent.ts:12-18, 104-120`
- Modify: `frontend/src/stores/agent.ts:51-106, 108-125, 281-298, 375-387, 407-447`
- Test: `frontend/src/stores/__tests__/agent.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/stores/__tests__/agent.spec.ts` 的 `describe('useAgentStore')` 内（仿照现有 radiomics progress 测试，437-468 行）追加：

```ts
  it('tracks thinking stream from SSE and clears it on stream end', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    await store.sendMessage('你好')
    const es = MockEventSource.instances[0]

    es.emit('agent', { thinking: { text: '先分析', done: false }, running: true })
    expect(store.currentThinking).toEqual({ text: '先分析', done: false })
    expect(store.busy).toBe(true)
    // thinking 事件不带 messages 字段时，现有消息不受影响
    expect(store.messages).toEqual([{ role: 'user', content: '你好' }])

    es.emit('agent', { thinking: { text: '先分析再回答', done: true }, running: true })
    expect(store.currentThinking).toEqual({ text: '先分析再回答', done: true })

    es.emit('agent_end', {})
    expect(store.currentThinking).toBeNull()
    expect(store.busy).toBe(false)
  })

  it('clears current thinking when an error payload arrives', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    await store.sendMessage('你好')
    const es = MockEventSource.instances[0]

    es.emit('agent', { thinking: { text: '思考中', done: false }, running: true })
    expect(store.currentThinking).not.toBeNull()

    es.emit('agent', { ...mockState(), messages: [], error: 'stream error: boom' })
    expect(store.currentThinking).toBeNull()
    expect(store.busy).toBe(false)
  })

  it('stop clears current thinking', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    await store.sendMessage('你好')
    const es = MockEventSource.instances[0]
    es.emit('agent', { thinking: { text: '思考中', done: false }, running: true })
    expect(store.currentThinking).not.toBeNull()

    await store.stop()

    expect(store.currentThinking).toBeNull()
    expect(store.busy).toBe(false)
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test:unit -- src/stores/__tests__/agent.spec.ts`
Expected: FAIL — `store.currentThinking` 为 undefined / TS 类型错误

- [ ] **Step 3: 实现类型与 store**

(a) `frontend/src/api/agent.ts`：`AgentMessage`（12-18 行）加字段：

```ts
export interface AgentMessage {
  role: string
  content: string
  timestamp?: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
  reasoning_content?: string
}
```

在 `RadiomicsProgress` 接口后新增：

```ts
export interface ThinkingState {
  text: string
  done: boolean
}
```

`AgentState`（104-120 行）加字段（放在 `radiomics_progress` 后）：

```ts
  thinking?: ThinkingState | null
```

(b) `frontend/src/stores/agent.ts`：

import 类型（6-18 行的 type import 列表加 `ThinkingState`）。

在 `radiomicsProgress` 声明（51 行）后新增：

```ts
  // 当前轮 LLM 的流式思考内容（推理模型的 reasoning_content；null 表示无）。
  // 独立于 messages：快照会整体替换 messages，流式文本必须走独立 ref。
  const currentThinking = ref<ThinkingState | null>(null)
```

`applyState`（58-106 行）修改两处。(1) error 分支（59-63 行）内加清空：

```ts
    if (state.error) {
      // 流式运行出错：保留现有消息，仅提示错误并解除忙碌。
      busy.value = false
      currentThinking.value = null
      ElMessage.error(state.error)
    }
```

(2) 字段合并区（97-99 行 `radiomics_progress` 之后）加 thinking 合并：

`resetInternalState`（108-125 行）在 `radiomicsProgress.value = null` 后加：

```ts
    currentThinking.value = null
```

`connect()` 的 `onEnd`（281-298 行）在 `radiomicsProgress.value = null` 后加：

```ts
        currentThinking.value = null
```

`stop()`（375-387 行）的 `finally` 在 `radiomicsProgress.value = null` 后加：

```ts
      currentThinking.value = null
```

return 导出列表（407-447 行）在 `radiomicsProgress` 后加 `currentThinking`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm run test:unit -- src/stores/__tests__/agent.spec.ts`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/agent.ts frontend/src/stores/agent.ts frontend/src/stores/__tests__/agent.spec.ts
git commit -m "feat(frontend): track streaming thinking state in agent store"
```

---

### Task 6: AgentChat.vue 渲染思考内容

两处 UI：(1) 流式期间消息列表末尾的"思考过程"气泡（实时滚动）；(2) assistant 消息气泡内的可折叠"思考过程"区块（默认折叠，数据来自消息的 `reasoning_content`）。非推理模型无 `reasoning_content`，两处都不渲染，行为与现状一致。

**Files:**
- Modify: `frontend/src/components/AgentChat.vue`
- Test: `frontend/src/components/__tests__/AgentChat.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/components/__tests__/AgentChat.spec.ts` 的 `describe('AgentChat')` 内追加：

```ts
  it('renders streaming thinking bubble while busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.currentThinking = { text: '正在分析数据…', done: false }

    const wrapper = setupWrapper()
    await flushPromises()

    const bubble = wrapper.find('.thinking-stream')
    expect(bubble.exists()).toBe(true)
    expect(bubble.text()).toContain('思考过程')
    expect(bubble.text()).toContain('正在分析数据…')
  })

  it('hides streaming bubble when thinking is done or not busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.currentThinking = { text: '想完了', done: true }

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.thinking-stream').exists()).toBe(false)
  })

  it('renders collapsed reasoning block for assistant messages and expands on click', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      { role: 'assistant', content: '答案', reasoning_content: '完整的思考过程' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const toggle = wrapper.find('.reasoning-toggle')
    expect(toggle.exists()).toBe(true)
    const reasoning = wrapper.find('.reasoning-content')
    expect(reasoning.exists()).toBe(true)
    expect(reasoning.isVisible()).toBe(false)

    await toggle.trigger('click')
    expect(wrapper.find('.reasoning-content').isVisible()).toBe(true)
    expect(wrapper.find('.reasoning-content').text()).toContain('完整的思考过程')
  })

  it('does not render reasoning block for messages without reasoning_content', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'assistant', content: '普通回复' }]

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.reasoning-toggle').exists()).toBe(false)
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AgentChat.spec.ts`
Expected: FAIL — `.thinking-stream` / `.reasoning-toggle` 不存在

- [ ] **Step 3: 实现渲染**

(a) 模板：在 assistant 消息气泡内、工具调用 tag 之前插入可折叠思考区块。`AgentChat.vue` 42-49 行附近，把：

```html
              <div
                v-if="message.role === 'tool'"
                class="message-tool-call"
              >
```

改为（在其前插入 reasoning-block）：

```html
              <div
                v-if="message.role === 'assistant' && message.reasoning_content"
                class="reasoning-block"
              >
                <el-button
                  link
                  size="small"
                  class="reasoning-toggle"
                  :aria-label="
                    isReasoningExpanded(index) ? '收起思考过程' : '展开思考过程'
                  "
                  @click="toggleReasoning(index)"
                >
                  {{ isReasoningExpanded(index) ? '收起' : '展开' }}思考过程
                </el-button>
                <div
                  v-show="isReasoningExpanded(index)"
                  class="reasoning-content"
                >
                  {{ message.reasoning_content }}
                </div>
              </div>
              <div
                v-if="message.role === 'tool'"
                class="message-tool-call"
              >
```

(b) 模板：消息列表 `v-for` 循环结束后（87 行 `</div>` 之后、88 行 `</div>` 之前）插入流式思考气泡：

```html
        <div
          v-if="showThinkingStream"
          class="message-row message-row--assistant"
        >
          <AgentAvatar class="message-avatar" />
          <div class="message-main message-main--assistant">
            <div class="message-bubble message-bubble--assistant thinking-stream">
              <div class="thinking-stream-header">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>思考过程</span>
              </div>
              <div class="thinking-stream-content">{{ agentStore.currentThinking?.text }}</div>
            </div>
          </div>
        </div>
```

(c) 脚本：在 `expandedToolIndexes` 声明（201 行）后新增：

```ts
/** 记录用户手动展开/收起的思考过程区块索引（默认折叠）。 */
const expandedReasoningIndexes = ref<Record<number, boolean>>({})

function isReasoningExpanded(index: number): boolean {
  return !!expandedReasoningIndexes.value[index]
}

function toggleReasoning(index: number): void {
  expandedReasoningIndexes.value[index] = !expandedReasoningIndexes.value[index]
}

/** 流式思考气泡：busy 且当前轮思考未结束时显示。 */
const showThinkingStream = computed(() => {
  const thinking = agentStore.currentThinking
  return (
    agentStore.busy && !!thinking && !thinking.done && thinking.text.length > 0
  )
})
```

(d) 脚本：在现有 `watchEffect`（323-328 行）后新增流式滚动：

```ts
// 流式思考文本更新时保持贴底滚动。
watchEffect(async () => {
  if (agentStore.currentThinking?.text) {
    await nextTick()
    scrollToBottom()
  }
})
```

(e) 样式：在 `<style scoped>` 中 `.tool-toggle` 规则后新增：

```css
.reasoning-block {
  margin-bottom: 0.25rem;
}

.reasoning-content {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  border-left: 2px solid var(--app-border);
  padding-left: 0.5rem;
  margin-top: 0.25rem;
}

.thinking-stream {
  width: 100%;
}

.thinking-stream-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  color: var(--app-text-muted);
  font-size: 0.875rem;
  margin-bottom: 0.25rem;
}

.thinking-stream-content {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  border-left: 2px solid var(--app-border);
  padding-left: 0.5rem;
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AgentChat.spec.ts`
Expected: 全部 PASS

- [ ] **Step 5: 类型检查与 lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/components/__tests__/AgentChat.spec.ts
git commit -m "feat(frontend): render streaming thinking bubble and collapsible reasoning blocks"
```

---

### Task 7: 全量回归与手动端到端验证

**Files:** 无（仅运行验证）

- [ ] **Step 1: 后端全量测试**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全部 PASS（重点确认 `test_agent_graph.py`、`test_api_agent.py`、`test_agent_nodes.py`、`test_sse_bridge.py` 无回归）

- [ ] **Step 2: 前端全量测试**

Run: `cd frontend && npm run test:unit`
Expected: 全部 PASS

- [ ] **Step 3: 手动端到端验证（需要真实 DEEPSEEK_API_KEY）**

1. 启动后端（`main.py`）与前端（`cd frontend && npm run dev`）；
2. 新建对话，模型选 **DeepSeek-V4 Flash**，发送一条消息（如"你好，介绍一下你自己"）；
3. 预期：消息列表末尾出现"思考过程"气泡，文本实时滚动增长；回复到达后气泡消失，assistant 消息内出现折叠的"展开思考过程"按钮，点击可展开完整思考链；
4. 刷新页面：历史 assistant 消息仍可展开思考链；
5. 发送一条会触发工具的消息（如"列出当前目录"），确认流式思考与工具调用 tag 并存、不互相干扰；
6. 模型改选 **DeepSeek-V4 Pro** 新建对话发消息：不出现任何思考 UI，行为与改造前一致。

若第 3 步看不到思考内容，优先排查：DeepSeek 流式 delta 的 `reasoning_content` 字段结构是否与 `_stream_chat_completion` 的解析一致（用一小段脚本打印原始 chunk 核对）。

- [ ] **Step 4: 最终 Commit（如有修复）**

```bash
git add -A
git commit -m "chore: finalize agent thinking stream feature"
```

---

## 自审记录

- **Spec 覆盖**：spec 的 7 个设计节（流式改造/旁路事件/persist 开关/透传/前端类型与 store/渲染/错误边界）分别对应 Task 2/2/1/4/5/6/2+7；测试计划各项对应 Task 1-6 的测试步骤；风险表的"delta 结构验证"对应 Task 7 Step 3 的排查指引。
- **类型一致性**：`_publish_thinking(thread_id, text, done)`、`_stream_chat_completion(api_key, base_url, model, messages, tools, thread_id)`、`ThinkingState{text,done}`、`currentThinking`、`showThinkingStream`、`isReasoningExpanded/toggleReasoning` 在前后任务间命名一致；Task 3 的 mock seam 与 Task 2 的函数名一致。
- **已知取舍**：Task 2 同时构造 ChatOpenAI（供工具内部规划调用）与 OpenAI 客户端（流式），是有意的最小改动——`build_tools` 契约不变。
