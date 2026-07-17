# Agent 自动审批模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Agent 聊天界面模型选择器上方加"自动审批"开关，开启后全部六类 HITL 确认操作跳过人工确认，图不中断一次跑完，且支持会话中实时切换。

**Architecture:** 开关状态后端存 `app.state.agent_auto_approve`（thread_id → bool，仿 `agent_llm_models`）；每次运行开始经 `_agent_config` 注入 `config.configurable.auto_approve`；`route_after_process` 读 config，开启时路由到新增 `auto_confirm` 节点（置 `confirmed=True`）直接进 `execute_confirmed`。新增 `PUT /threads/{id}/auto-approve` 支持实时切换。前端 store 持 `autoApprove` ref，建/载线程时随请求发出，`AgentChat.vue` 在 `.chat-status` 与 `.message-input-area` 之间新增一行右对齐 `el-switch`。

**Tech Stack:** Python 3.11+ / FastAPI / LangGraph（pytest）；Vue 3 + Element Plus + Pinia + TypeScript（vitest + @vue/test-utils）。

**Spec:** `docs/superpowers/specs/2026-07-17-auto-approve-mode-design.md`

**已知边界（规格已确认，勿改动）：** 已挂起的审批项不自动确认；运行途中切换在下一次运行/恢复时生效；`auto_approve` 不持久化，服务重启/页面刷新后默认关闭。

---

### Task 1: 图节点 — `route_after_process` 加 `auto_confirm` 分支

**Files:**
- Modify: `app/agent/nodes.py:235-237`（替换 `route_after_process`，新增 `auto_confirm`）
- Modify: `app/agent/graph.py`（注册节点与边）
- Test: `tests/test_agent_nodes.py`（路由单元测试）
- Test: `tests/test_agent_graph.py`（图集成测试）

- [ ] **Step 1: 写失败的路由单元测试**

在 `tests/test_agent_nodes.py` 中，先把第 7 行的导入改为：

```python
from app.agent.nodes import _build_llm, _resolve_api_key, auto_confirm, call_llm, route_after_process
```

然后在文件末尾追加：

```python
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
```

- [ ] **Step 2: 写失败的图集成测试**

在 `tests/test_agent_graph.py` 末尾追加（模式仿照 `test_graph_interrupts_on_system_command`，54-83 行）：

```python
def test_graph_auto_approve_skips_interrupt(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-v4-pro"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="list files")]

    graph = create_agent_graph()
    config = {"configurable": {"thread_id": "test-auto-approve", "auto_approve": True}}

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
        assert not any("__interrupt__" in e for e in events)

        final = graph.get_state(config).values

    tool_msg = _find_result_tool_message(final["messages"], tool_call_id="call_list")
    assert tool_msg is not None
    parsed = json.loads(tool_msg.content)
    assert parsed["tool"] == "list_directory"
    assert "result" in parsed
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_agent_nodes.py tests/test_agent_graph.py -v`
Expected: FAIL —— `ImportError: cannot import name 'auto_confirm' from 'app.agent.nodes'`（节点测试在收集期失败），图测试同样因 import 失败或路由断言失败。

- [ ] **Step 4: 实现 `nodes.py` 改动**

把 `app/agent/nodes.py` 235-237 行的 `route_after_process` 整体替换为（`RunnableConfig` 与 `Literal` 已在文件头部导入，无需新增 import）：

```python
def route_after_process(
    state: AgentState, config: RunnableConfig
) -> Literal["human_review", "auto_confirm", "call_llm"]:
    """根据是否有待确认的中断决定路由；自动审批开启时跳过人工确认。"""
    if not state.get("interrupt_type"):
        return "call_llm"
    if config.get("configurable", {}).get("auto_approve"):
        return "auto_confirm"
    return "human_review"


def auto_confirm(state: AgentState) -> dict:
    """自动审批：跳过 human_review，直接标记为已确认。"""
    return {"confirmed": True}
```

- [ ] **Step 5: 实现 `graph.py` 改动**

`app/agent/graph.py` 全文 29 行，整体替换为：

```python
from langgraph.graph import StateGraph, END, START
from app.agent.state import AgentState
from app.agent.nodes import (
    call_llm,
    process_tool_calls,
    human_review,
    auto_confirm,
    execute_confirmed,
    should_continue,
    route_after_process,
)


def create_agent_graph(checkpointer=None):
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
    builder = StateGraph(AgentState)
    builder.add_node("call_llm", call_llm)
    builder.add_node("process_tool_calls", process_tool_calls)
    builder.add_node("human_review", human_review)
    builder.add_node("auto_confirm", auto_confirm)
    builder.add_node("execute_confirmed", execute_confirmed)

    builder.add_edge(START, "call_llm")
    builder.add_conditional_edges("call_llm", should_continue, {"process_tool_calls": "process_tool_calls", "__end__": END})
    builder.add_conditional_edges("process_tool_calls", route_after_process, {"human_review": "human_review", "auto_confirm": "auto_confirm", "call_llm": "call_llm"})
    builder.add_edge("human_review", "execute_confirmed")
    builder.add_edge("auto_confirm", "execute_confirmed")
    builder.add_edge("execute_confirmed", "call_llm")

    return builder.compile(checkpointer=checkpointer)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_agent_nodes.py tests/test_agent_graph.py -v`
Expected: 全部 PASS（含原有中断路径测试不受影响）。

- [ ] **Step 7: Commit**

```bash
git add app/agent/nodes.py app/agent/graph.py tests/test_agent_nodes.py tests/test_agent_graph.py
git commit -m "feat(agent): 自动审批开启时 route_after_process 走 auto_confirm 跳过人工确认"
```

---

### Task 2: API 层 — `auto_approve` 配置链路与 `PUT` 实时切换接口

**Files:**
- Modify: `app/api/__init__.py:34`（初始化字典）
- Modify: `app/api/agent.py`（请求模型 35-58、`_agent_config` 67-90、建线程 285-309、删线程 348-372、载线程 390-411、新增端点）
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 写失败的 API 测试**

`tests/test_api_agent.py` 第 13 行导入改为：

```python
from app.api.agent import get_agent_graph, _unanswered_tool_call_ids, _agent_config
```

文件末尾追加：

```python
def test_create_thread_with_auto_approve(client, app):
    project = _create_project(client)
    response = client.post(
        f"/api/agent/threads?project_id={project['id']}",
        json={"api_key": "", "llm_model": "deepseek-v4-pro", "auto_approve": True},
    )
    assert response.status_code == 201, response.text
    thread_id = response.json()["thread_id"]
    assert app.state.agent_auto_approve[thread_id] is True


def test_thread_auto_approve_defaults_false(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    assert app.state.agent_auto_approve[thread_id] is False


def test_resume_thread_updates_auto_approve(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.post(
        f"/api/agent/threads/{thread_id}/resume",
        json={"api_key": "", "llm_model": "deepseek-v4-pro", "auto_approve": True},
    )
    assert response.status_code == 200, response.text
    assert app.state.agent_auto_approve[thread_id] is True


def test_set_auto_approve(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.put(
        f"/api/agent/threads/{thread_id}/auto-approve", json={"enabled": True}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"auto_approve": True}
    assert app.state.agent_auto_approve[thread_id] is True

    response = client.put(
        f"/api/agent/threads/{thread_id}/auto-approve", json={"enabled": False}
    )
    assert response.status_code == 200, response.text
    assert app.state.agent_auto_approve[thread_id] is False


def test_set_auto_approve_thread_not_found(client):
    response = client.put(
        "/api/agent/threads/nonexistent/auto-approve", json={"enabled": True}
    )
    assert response.status_code == 404, response.text


def test_agent_config_carries_auto_approve(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    client.put(f"/api/agent/threads/{thread_id}/auto-approve", json={"enabled": True})

    config = asyncio.run(_agent_config(thread_id, app))

    assert config["configurable"]["auto_approve"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_agent.py -v -k auto_approve`
Expected: FAIL —— `AttributeError: 'State' object has no attribute 'agent_auto_approve'`，且 PUT 请求返回 404/405（路由不存在）。

- [ ] **Step 3: 初始化 `app.state.agent_auto_approve`**

`app/api/__init__.py` 第 34 行 `app.state.agent_llm_models = {}` 之后新增一行：

```python
    app.state.agent_auto_approve = {}
```

- [ ] **Step 4: 请求模型加字段**

`app/api/agent.py` 的 `CreateThreadRequest`（35-39 行）改为：

```python
class CreateThreadRequest(BaseModel):
    """Request body for creating an agent thread."""

    api_key: str = ""
    llm_model: Literal["deepseek-v4-pro", "deepseek-v4-flash"] = "deepseek-v4-pro"
    auto_approve: bool = False
```

`LoadThreadRequest`（54-58 行）同样加 `auto_approve: bool = False`：

```python
class LoadThreadRequest(BaseModel):
    """Request body for resuming an existing thread."""

    api_key: str = ""
    llm_model: Literal["deepseek-v4-pro", "deepseek-v4-flash"] = "deepseek-v4-pro"
    auto_approve: bool = False
```

在 `UpdatePlanRequest`（42-45 行）之后新增：

```python
class AutoApproveRequest(BaseModel):
    """Request body for toggling auto-approve on a thread."""

    enabled: bool
```

- [ ] **Step 5: `_agent_config` 注入开关值**

`app/api/agent.py` 67-90 行 `_agent_config` 的 return 改为：

```python
    return {
        "configurable": {
            "thread_id": thread_id,
            "api_key": api_key,
            "llm_model": llm_model,
            "auto_approve": getattr(app.state, "agent_auto_approve", {}).get(
                thread_id, False
            ),
        }
    }
```

- [ ] **Step 6: 建/载/删线程维护字典**

- `create_thread`（约 305 行 `request.app.state.agent_llm_models[thread_id] = llm_model` 之后）加：

```python
    request.app.state.agent_auto_approve[thread_id] = payload.auto_approve
```

- `delete_thread`（约 366 行 `request.app.state.agent_llm_models.pop(thread_id, None)` 之后）加：

```python
        request.app.state.agent_auto_approve.pop(thread_id, None)
```

- `resume_thread`（约 404 行 `request.app.state.agent_llm_models[thread_id] = payload.llm_model` 之后）加：

```python
    request.app.state.agent_auto_approve[thread_id] = payload.auto_approve
```

- [ ] **Step 7: 新增 PUT 端点**

在 `resume_thread` 函数结束（约 411 行 `return payload_out`）之后、`send_message` 装饰器之前插入：

```python
@router.put("/threads/{thread_id}/auto-approve", response_model=Dict[str, Any])
async def set_auto_approve(
    thread_id: str,
    payload: AutoApproveRequest,
    request: Request,
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Toggle auto-approve for a thread; applies from the next graph run."""
    if await _run_store_sync(store.get_thread_meta, thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    request.app.state.agent_auto_approve[thread_id] = payload.enabled
    return {"auto_approve": payload.enabled}
```

- [ ] **Step 8: 运行测试确认通过**

Run: `python -m pytest tests/test_api_agent.py -v`
Expected: 全部 PASS（含既有用例）。

- [ ] **Step 9: Commit**

```bash
git add app/api/__init__.py app/api/agent.py tests/test_api_agent.py
git commit -m "feat(api): auto_approve 线程级配置与 PUT /threads/{id}/auto-approve 接口"
```

---

### Task 3: 前端 API 层与 Pinia store

**Files:**
- Modify: `frontend/src/api/agent.ts`（请求接口 121-124、148-151，新增 `setAutoApprove`）
- Modify: `frontend/src/stores/agent.ts`（ref、action、三处请求载荷、导出）
- Test: `frontend/src/stores/__tests__/agent.spec.ts`

- [ ] **Step 1: 写失败的 store 测试**

在 `frontend/src/stores/__tests__/agent.spec.ts` 的 `describe('useAgentStore', ...)` 块内末尾（最后一个 `})` 闭合之前）追加：

```ts
  describe('setAutoApprove', () => {
    it('updates locally without an active thread', async () => {
      const store = useAgentStore()

      await store.setAutoApprove(true)

      expect(store.autoApprove).toBe(true)
      expect(vi.mocked(client.put)).not.toHaveBeenCalled()
    })

    it('sends the flag to the backend when a thread is active', async () => {
      const store = useAgentStore()
      await store.ensureThread('project-1', '', 'deepseek-v4-flash')
      vi.mocked(client.put).mockResolvedValue({ data: { auto_approve: true } })

      await store.setAutoApprove(true)

      expect(client.put).toHaveBeenCalledWith('/agent/threads/thread-1/auto-approve', {
        enabled: true,
      })
      expect(store.autoApprove).toBe(true)
    })

    it('rolls back on API failure', async () => {
      const store = useAgentStore()
      await store.ensureThread('project-1', '', 'deepseek-v4-flash')
      vi.mocked(client.put).mockRejectedValue(new Error('boom'))

      await expect(store.setAutoApprove(true)).rejects.toThrow('boom')

      expect(store.autoApprove).toBe(false)
    })

    it('includes auto_approve when creating a thread', async () => {
      const store = useAgentStore()
      await store.setAutoApprove(true)

      await store.createThread('project-1', 'sk-test', 'deepseek-v4-flash')

      expect(client.post).toHaveBeenCalledWith(
        '/agent/threads',
        { api_key: 'sk-test', llm_model: 'deepseek-v4-flash', auto_approve: true },
        { params: { project_id: 'project-1' } }
      )
    })
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/agent.spec.ts`
Expected: FAIL —— `store.setAutoApprove is not a function` / `store.autoApprove is undefined`。

- [ ] **Step 3: 实现 `api/agent.ts` 改动**

`CreateThreadRequest`（121-124 行）与 `LoadThreadRequest`（148-151 行）各加一个字段：

```ts
export interface CreateThreadRequest {
  api_key: string
  llm_model: string
  auto_approve: boolean
}
```

```ts
export interface LoadThreadRequest {
  api_key: string
  llm_model: string
  auto_approve: boolean
}
```

在 `cancel`（206-209 行）之后新增：

```ts
export const setAutoApprove = async (
  threadId: string,
  enabled: boolean
): Promise<{ auto_approve: boolean }> => {
  const res = await client.put(
    `/agent/threads/${encodeURIComponent(threadId)}/auto-approve`,
    { enabled }
  )
  return res.data
}
```

- [ ] **Step 4: 实现 `stores/agent.ts` 改动**

a) 在 `const busy = ref(false)`（34 行）之后新增：

```ts
  // 自动审批：开启后后端跳过全部人工确认中断，直接执行挂起操作。
  const autoApprove = ref(false)
```

b) 新增 action（放在 `cancel` 函数之后）：

```ts
  async function setAutoApprove(enabled: boolean): Promise<void> {
    const previous = autoApprove.value
    autoApprove.value = enabled
    if (!threadId.value) return
    try {
      await api.setAutoApprove(threadId.value, enabled)
    } catch (err) {
      // 回滚乐观更新；错误提示由 axios 拦截器统一 toast。
      autoApprove.value = previous
      throw err
    }
  }
```

c) 三处请求载荷加字段。`ensureThread`（131-134 行）与 `createThread`（193-196 行）的 `api.createThread(projectId, {...})` 都改为：

```ts
    const { thread_id } = await api.createThread(projectId, {
      api_key: apiKey,
      llm_model: llmModel,
      auto_approve: autoApprove.value,
    })
```

`loadThread`（169-172 行）的 `api.resumeThread(...)` 改为：

```ts
    const state = await api.resumeThread(threadIdToLoad, {
      api_key: apiKey,
      llm_model: llmModel,
      auto_approve: autoApprove.value,
    })
```

d) store 的 return 块（340-371 行）中，`busy,` 之后加 `autoApprove,`，`cancel,` 之后加 `setAutoApprove,`。

- [ ] **Step 5: 更新两处既有断言（载荷形状变化）**

实现后既有测试的两处 `toHaveBeenCalledWith` 精确匹配会因新字段失败，需同步更新：

- 约 257-260 行（createThread 断言）改为：

```ts
    expect(agentApi.createThread).toHaveBeenCalledWith('project-1', {
      api_key: 'sk-test',
      llm_model: 'deepseek-v4-flash',
      auto_approve: false,
    })
```

- 约 296-299 行（resumeThread 断言）改为：

```ts
    expect(agentApi.resumeThread).toHaveBeenCalledWith('thread-load', {
      api_key: 'sk-test',
      llm_model: 'deepseek-v4-flash',
      auto_approve: false,
    })
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/stores/__tests__/agent.spec.ts`
Expected: 全部 PASS（新增 4 条 + 既有用例）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/agent.ts frontend/src/stores/agent.ts frontend/src/stores/__tests__/agent.spec.ts
git commit -m "feat(frontend): agent store 增加 autoApprove 状态与 setAutoApprove action"
```

---

### Task 4: `AgentChat.vue` 开关 UI（模型选择器上方）

**Files:**
- Modify: `frontend/src/components/AgentChat.vue`（模板 90-92 行之间、script、style）
- Test: `frontend/src/components/__tests__/AgentChat.spec.ts`

- [ ] **Step 1: 写失败的组件测试**

在 `frontend/src/components/__tests__/AgentChat.spec.ts` 的 `describe('AgentChat', ...)` 块内追加：

```ts
  it('renders auto-approve switch above the model selector and toggles the store', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()
    const agentStore = useAgentStore()

    const wrapper = setupWrapper()
    await flushPromises()

    const row = wrapper.find('.auto-approve-row')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('自动审批')

    // DOM 顺序：开关行必须在输入区（含模型选择器）之前。
    const html = wrapper.html()
    expect(html.indexOf('auto-approve-row')).toBeLessThan(html.indexOf('model-selector'))

    await wrapper.find('.el-switch').trigger('click')
    expect(agentStore.autoApprove).toBe(true)
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/components/__tests__/AgentChat.spec.ts`
Expected: FAIL —— `row.exists()` 为 false（`.auto-approve-row` 不存在）。

- [ ] **Step 3: 实现模板改动**

在 `frontend/src/components/AgentChat.vue` 中，`.chat-status` 的闭合 `</div>`（90 行）与 `<div class="message-input-area">`（92 行）之间插入：

```html
      <div class="auto-approve-row">
        <span class="auto-approve-label">自动审批</span>
        <el-switch
          :model-value="agentStore.autoApprove"
          aria-label="自动审批"
          @change="handleAutoApproveChange"
        />
      </div>
```

- [ ] **Step 4: 实现 script 改动**

在 `inputPlaceholder` computed（206-210 行）之后新增：

```ts
function handleAutoApproveChange(value: string | number | boolean): void {
  void agentStore.setAutoApprove(Boolean(value))
}
```

（`agentStore` 已在 147 行实例化，无需新增 import。）

- [ ] **Step 5: 实现样式改动**

在 `.chat-status--idle` 规则（431-433 行）之后、`.message-input-area`（435 行）之前新增：

```css
.auto-approve-row {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.5rem;
  padding: 0 0.25rem 0.25rem;
  color: #909399;
  font-size: 0.75rem;
}
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/components/__tests__/AgentChat.spec.ts`
Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/components/__tests__/AgentChat.spec.ts
git commit -m "feat(frontend): 模型选择器上方新增自动审批开关"
```

---

### Task 5: 全量验证

**Files:** 无（仅运行检查）

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS，无回归。

- [ ] **Step 2: 前端全量测试**

Run: `cd frontend && npm run test:unit`
Expected: 全部 PASS，无回归。

- [ ] **Step 3: 前端类型检查与 lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 无错误输出。

## Self-Review 记录

- 规格覆盖：后端图分支（Task 1）、API 链路与 PUT 接口（Task 2）、前端 api/store（Task 3）、开关 UI 位置（Task 4）、错误处理（Task 2 404 / Task 3 回滚）、测试（各 Task 内）——规格各节均有对应任务。
- 类型一致性：后端 `AutoApproveRequest.enabled` ↔ 前端 `setAutoApprove(threadId, enabled)` 请求体 `{ enabled }`；store `autoApprove` ↔ 组件 `agentStore.autoApprove` / `handleAutoApproveChange`；`auto_approve` 字段名前后端一致。
- 边界语义：Task 1 不改变 `human_review` 既有行为；已挂起项仍走原 confirm/cancel 流程，符合规格。
