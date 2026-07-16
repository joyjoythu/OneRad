# Agent 聊天停止按钮实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agent 运行中发送按钮变为停止按钮，按下后取消后端流式任务、修复消息历史（补"已停止" ToolMessage）并保留上下文，用户可立即继续对话。

**Architecture:** 对齐项目现有 pipeline 取消模式（`app/api/runs.py` + `app/api/runner.py`）：新增 thread_id→asyncio.Task 映射，stop 端点 `task.cancel()` 后检查检查点，为未应答的 tool_calls 补 ToolMessage 并通过 SSE 推送最终状态；前端用条件渲染把发送按钮换成停止按钮。

**Tech Stack:** FastAPI + LangGraph（AsyncSqliteSaver 检查点）、Vue 3 + Pinia + Element Plus、pytest + vitest。

**设计依据:** `docs/superpowers/specs/2026-07-16-agent-stop-button-design.md`（已批准）。

---

### Task 1: 后端辅助函数 `_unanswered_tool_call_ids`

**Files:**
- Modify: `app/api/agent.py`（在 `_make_message` 之后添加）
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 写失败的单元测试**

在 `tests/test_api_agent.py` 顶部 import 区追加：

```python
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.api.agent import get_agent_graph, _unanswered_tool_call_ids
```

（替换原有的 `from app.api.agent import get_agent_graph` 一行。）

文件末尾追加：

```python
def test_unanswered_tool_call_ids_all_answered():
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "list_directory", "args": {}}],
        ),
        ToolMessage(content="{}", tool_call_id="call_1"),
    ]
    assert _unanswered_tool_call_ids(messages) == []


def test_unanswered_tool_call_ids_partial():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "a", "args": {}},
                {"id": "call_2", "name": "b", "args": {}},
            ],
        ),
        ToolMessage(content="{}", tool_call_id="call_1"),
    ]
    assert _unanswered_tool_call_ids(messages) == ["call_2"]


def test_unanswered_tool_call_ids_without_tool_calls():
    assert _unanswered_tool_call_ids([HumanMessage(content="hi")]) == []


def test_unanswered_tool_call_ids_empty_history():
    assert _unanswered_tool_call_ids([]) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -q -k unanswered`
Expected: FAIL（`ImportError: cannot import name '_unanswered_tool_call_ids'`）

- [ ] **Step 3: 实现辅助函数**

在 `app/api/agent.py` 的 `_make_message` 函数之后插入：

```python
def _unanswered_tool_call_ids(messages: List[Any]) -> List[str]:
    """返回末条 assistant 消息的 tool_calls 中尚无 ToolMessage 应答的 id。

    停止运行后用于修复历史：为这些 id 各补一条 ToolMessage，
    避免下次调用 LLM 时报 400（tool_calls 缺少响应）。
    """
    if not messages:
        return []
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return []
    answered = {
        getattr(msg, "tool_call_id", None)
        for msg in messages
        if isinstance(msg, ToolMessage)
    }
    missing: List[str] = []
    for tc in tool_calls:
        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
        if tc_id and tc_id not in answered:
            missing.append(tc_id)
    return missing
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -q -k unanswered`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat(agent): add helper to find unanswered tool_call ids"
```

---

### Task 2: 后端流式任务登记（`agent_stream_tasks` 映射）

**Files:**
- Modify: `app/api/__init__.py:31`（lifespan）
- Modify: `app/api/agent.py`（`_start_stream`、`_stream_agent`）
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 写失败测试**

`tests/test_api_agent.py` 末尾追加：

```python
def test_stream_task_registered_and_cleaned_up(client, app):
    """流式运行期间任务应登记在 agent_stream_tasks，结束后清理。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    async def fake_astream(input_value=None, config=None, stream_mode=None):
        yield {
            "messages": [],
            "interrupt_type": None,
            "operation_log": ["started"],
        }

    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={"interrupt_type": None})
    )
    mock_graph.astream = fake_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hello"},
    )
    assert response.status_code == 202, response.text

    # 等待后台流式任务完成
    deadline = time.time() + 2
    while time.time() < deadline and thread_id in app.state.active_agent_streams:
        time.sleep(0.05)
    assert thread_id not in app.state.active_agent_streams
    assert thread_id not in app.state.agent_stream_tasks
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -q -k registered_and_cleaned`
Expected: FAIL（`AttributeError: 'State' object has no attribute 'agent_stream_tasks'`）

- [ ] **Step 3: 实现任务登记**

`app/api/__init__.py` lifespan 中，`app.state.active_agent_streams = set()` 之后加一行：

```python
    app.state.agent_stream_tasks = {}
```

`app/api/agent.py` 的 `_start_stream`，把 create_task 结果登记进映射：

```python
    app.state.active_agent_streams.add(thread_id)
    try:
        config = await _agent_config(thread_id, app)
        task = asyncio.create_task(
            _stream_agent(thread_id, graph, config, bridge, app, input_value)
        )
        app.state.agent_stream_tasks[thread_id] = task
    except Exception:
        app.state.active_agent_streams.discard(thread_id)
        raise
```

`app/api/agent.py` 的 `_stream_agent` finally 块改为：

```python
    finally:
        app.state.active_agent_streams.discard(thread_id)
        app.state.pipeline_tasks.discard(task)
        app.state.agent_stream_tasks.pop(thread_id, None)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -q`
Expected: 全部 passed（含原有 17 个测试无回归）

- [ ] **Step 5: Commit**

```bash
git add app/api/__init__.py app/api/agent.py tests/test_api_agent.py
git commit -m "feat(agent): track stream tasks per thread"
```

---

### Task 3: 后端 stop 端点（取消 + 历史修复 + 推送最终状态）

**Files:**
- Modify: `app/api/agent.py`（新增 `stop_stream` 端点，放在 `cancel_interrupt` 之后）
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 写失败测试**

`tests/test_api_agent.py` 末尾追加：

```python
def test_stop_conflict_when_not_running(client, app):
    """空闲线程上没有正在运行的任务，stop 应返回 409。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    response = client.post(f"/api/agent/threads/{thread_id}/stop")
    assert response.status_code == 409, response.text


def test_stop_cancels_stream_and_repairs_history(client, app):
    """stop 应取消活动流，并为未应答的 tool_calls 补「已停止」ToolMessage。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    dangling_messages = [
        HumanMessage(content="hi"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "list_directory", "args": {}}],
        ),
    ]
    repaired_messages = dangling_messages + [
        ToolMessage(
            content=json.dumps(
                {"cancelled": True, "reason": "用户停止了操作"}, ensure_ascii=False
            ),
            tool_call_id="call_1",
        )
    ]
    snapshots = [
        # ① send_message 发送前检查
        SimpleNamespace(values={"interrupt_type": None}),
        # ② stop 存在性检查
        SimpleNamespace(values={"interrupt_type": None}),
        # ③ 取消后读取：末条为未应答 tool_calls
        SimpleNamespace(values={"messages": dangling_messages}),
        # ④ 修复后读取：用于发布最终状态
        SimpleNamespace(
            values={
                "messages": repaired_messages,
                "operation_log": ["用户停止了当前任务"],
            }
        ),
    ]

    async def blocking_astream(input_value=None, config=None, stream_mode=None):
        yield {
            "messages": [],
            "interrupt_type": None,
            "operation_log": ["started"],
        }
        await asyncio.sleep(3600)

    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(side_effect=snapshots)
    mock_graph.astream = blocking_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hi"},
    )
    assert response.status_code == 202, response.text

    deadline = time.time() + 2
    while time.time() < deadline and thread_id not in app.state.agent_stream_tasks:
        time.sleep(0.05)
    assert thread_id in app.state.agent_stream_tasks

    response = client.post(f"/api/agent/threads/{thread_id}/stop")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "stopped"

    # 历史修复：补了一条 cancelled ToolMessage，并记录操作日志
    mock_graph.aupdate_state.assert_awaited_once()
    updates = mock_graph.aupdate_state.await_args.args[1]
    assert len(updates["messages"]) == 1
    tool_msg = updates["messages"][0]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "call_1"
    assert json.loads(tool_msg.content)["cancelled"] is True
    assert updates["operation_log"] == ["用户停止了当前任务"]

    # 任务收尾：线程离开 active 集合，映射清理
    assert thread_id not in app.state.active_agent_streams
    assert thread_id not in app.state.agent_stream_tasks

    # 最终状态已通过 SSE 桥发布
    events = app.state.event_bridge.store.list_sse_events("agent", thread_id)
    last_payload = json.loads(events[-1]["data"])
    assert last_payload["operation_log"] == ["用户停止了当前任务"]
    assert last_payload["messages"][-1]["role"] == "tool"
```

同时在文件顶部 import 区补充 `import asyncio`（若尚无）。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -q -k stop`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 实现 stop 端点**

`app/api/agent.py` 顶部 import 区补充：

```python
from contextlib import suppress
```

在 `cancel_interrupt` 之后、`thread_events` 之前插入新端点：

```python
@router.post(
    "/threads/{thread_id}/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def stop_stream(
    thread_id: str,
    request: Request,
    graph=Depends(get_agent_graph),
) -> Dict[str, Any]:
    """停止线程上正在运行的智能体流式任务，保留对话上下文。

    取消后台任务后，若消息历史末尾仍有未应答的 tool_calls，为每个缺失的
    tool_call_id 补一条「已停止」ToolMessage，避免下次调用 LLM 时因
    tool_calls 缺少响应而报 400。
    """
    config = await _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    task = request.app.state.agent_stream_tasks.get(thread_id)
    if thread_id not in request.app.state.active_agent_streams or task is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前没有正在运行的任务",
        )

    task.cancel()
    # 等待任务收尾（finally 清理集合与映射）。任务若已因其他异常结束，
    # 错误已由 _stream_agent 发布，这里不重复抛出。
    with suppress(asyncio.CancelledError, Exception):
        await task

    snapshot = await graph.aget_state(config)
    missing_ids = _unanswered_tool_call_ids(snapshot.values.get("messages", []))
    if missing_ids:
        await graph.aupdate_state(
            config,
            {
                "messages": [
                    ToolMessage(
                        content=json.dumps(
                            {"cancelled": True, "reason": "用户停止了操作"},
                            ensure_ascii=False,
                        ),
                        tool_call_id=tc_id,
                    )
                    for tc_id in missing_ids
                ],
                "operation_log": ["用户停止了当前任务"],
            },
        )
        snapshot = await graph.aget_state(config)

    bridge = get_bridge(request)
    await bridge.publish("agent", thread_id, _sync_payload(snapshot.values))
    return {"thread_id": thread_id, "status": "stopped"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -q`
Expected: 全部 passed

再跑后端全量：

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: 全部 passed（1 skipped 为既有跳过）

- [ ] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat(agent): add stop endpoint cancelling stream and repairing history"
```

---

### Task 4: 前端 API 与 store 的 `stop()`

**Files:**
- Modify: `frontend/src/api/agent.ts`
- Modify: `frontend/src/stores/agent.ts`
- Test: `frontend/src/stores/__tests__/agent.spec.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/stores/__tests__/agent.spec.ts` 中，`clears busy when an interrupt snapshot arrives` 测试之后追加：

```ts
  it('stop calls the stop API and clears busy', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    await store.sendMessage('Hello')
    expect(store.busy).toBe(true)

    await store.stop()

    expect(client.post).toHaveBeenCalledWith('/agent/threads/thread-1/stop')
    expect(store.busy).toBe(false)
  })

  it('stop clears busy even when the API fails', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    await store.sendMessage('Hello')
    expect(store.busy).toBe(true)
    vi.mocked(client.post).mockRejectedValueOnce(new Error('network error'))

    await expect(store.stop()).rejects.toThrow('network error')
    expect(store.busy).toBe(false)
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/agent.spec.ts`
Expected: FAIL（`store.stop is not a function`）

- [ ] **Step 3: 实现 stopAgent API 与 store.stop**

`frontend/src/api/agent.ts` 中 `cancel` 之后追加：

```ts
export const stopAgent = async (
  threadId: string
): Promise<{ thread_id: string; status: string }> => {
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/stop`
  )
  return res.data
}
```

`frontend/src/stores/agent.ts` 中 `cancel` 之后追加：

```ts
  async function stop(): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    try {
      await api.stopAgent(threadId.value)
    } finally {
      // 无论成功与否都复位忙碌；失败原因由 axios 拦截器 toast，
      // 若后端仍在运行，后续发送会被 409 兜底，状态自愈。
      busy.value = false
    }
  }
```

并在 store 的 return 对象中 `cancel,` 之后加一行 `stop,`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/stores/__tests__/agent.spec.ts`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/agent.ts frontend/src/stores/agent.ts frontend/src/stores/__tests__/agent.spec.ts
git commit -m "feat(agent): add stop action to frontend store"
```

---

### Task 5: 前端 AgentChat 停止按钮 + AgentView 接线

**Files:**
- Modify: `frontend/src/components/AgentChat.vue`
- Modify: `frontend/src/views/AgentView.vue:22-27`（AgentChat 标签）与 script
- Test: `frontend/src/components/__tests__/AgentChat.spec.ts`

- [ ] **Step 1: 调整既有测试 + 写失败测试**

`frontend/src/components/__tests__/AgentChat.spec.ts` 中，既有测试
`disables input and send button while the agent is busy` 改为
（busy 时发送按钮被停止按钮替换，不再存在）：

```ts
  it('disables input while the agent is busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
  })
```

随后追加两个新测试：

```ts
  it('shows a stop button while busy and emits stop on click', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true

    const wrapper = setupWrapper()
    await flushPromises()

    const stopButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('停止'))
    expect(stopButton).toBeDefined()
    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeUndefined()

    await stopButton!.trigger('click')
    expect(wrapper.emitted('stop')).toHaveLength(1)
  })

  it('shows the send button and no stop button when idle', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeDefined()
    const stopButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('停止'))
    expect(stopButton).toBeUndefined()
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/components/__tests__/AgentChat.spec.ts`
Expected: FAIL（找不到"停止"按钮）

- [ ] **Step 3: 实现按钮切换与事件接线**

`frontend/src/components/AgentChat.vue` 模板中，把发送按钮替换为：

```html
        <el-button
          v-if="agentStore.busy"
          type="danger"
          :icon="CircleClose"
          @click="handleStop"
        >
          停止
        </el-button>
        <el-button
          v-else
          type="primary"
          :icon="Promotion"
          :disabled="!canSend"
          @click="handleSend"
        >
          发送
        </el-button>
```

script 中：
- 图标 import 改为 `import { CircleClose, Loading, Promotion } from '@element-plus/icons-vue'`。
- emits 定义改为：

```ts
const emit = defineEmits<{
  'update:model': [model: string]
  'send-message': [content: string]
  'stop': []
}>()
```

- `handleSend` 之后追加：

```ts
function handleStop(): void {
  emit('stop')
}
```

`frontend/src/views/AgentView.vue`：
- AgentChat 标签加 `@stop="handleStop"`：

```html
        <AgentChat
          ref="agentChatRef"
          :model="selectedModel"
          @update:model="selectedModel = $event"
          @send-message="handleSendMessage"
          @stop="handleStop"
        />
```

- `handleSendMessage` 之后追加：

```ts
async function handleStop(): Promise<void> {
  try {
    await agentStore.stop()
  } catch {
    // errors handled by axios interceptor
  }
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/components/__tests__/AgentChat.spec.ts src/views/__tests__/AgentView.spec.ts`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/views/AgentView.vue frontend/src/components/__tests__/AgentChat.spec.ts
git commit -m "feat(agent): switch send button to stop button while running"
```

---

### Task 6: 全量验证

**Files:** 无（仅运行检查）

- [ ] **Step 1: 后端全量测试**

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: 全部 passed（1 skipped 为既有跳过）

- [ ] **Step 2: 前端全量测试**

Run: `cd frontend && npx vitest run`
Expected: 全部 passed

- [ ] **Step 3: 前端类型检查与 lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 无输出（通过）

- [ ] **Step 4: 前端生产构建**

Run: `cd frontend && npm run build`
Expected: `✓ built in ...`（chunk 体积警告为既有，可忽略）
