# 上下文用量指示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Agent 聊天对话框右下角显示当前上下文用量（最近一次 LLM 调用的输入 token 数及占 1M 窗口的百分比）。

**Architecture:** 后端 `call_llm` 节点从 `AIMessage.usage_metadata` 提取真实 token 用量存入 graph state，`_sync_payload` 附带上下文窗口大小，随现有 REST/SSE 链路推送；前端 store 接收后在输入区右侧渲染 badge。

**Tech Stack:** Python / LangGraph / langchain-openai / FastAPI / pytest；Vue 3 / Pinia / Element Plus / vitest。

**Spec:** `docs/superpowers/specs/2026-07-16-context-usage-indicator-design.md`

**环境说明：** 后端测试用项目 venv：Windows Git Bash 下为 `.venv/Scripts/python -m pytest`；前端命令都在 `frontend/` 目录下执行（`npx vitest run ...`）。

---

### Task 1: 后端——call_llm 提取 usage_metadata 存入 state

**Files:**
- Modify: `app/agent/state.py`（新增 `context_usage` 字段）
- Modify: `app/agent/nodes.py`（`call_llm` 提取用量 + 新增 `_extract_context_usage` 辅助函数）
- Test: `tests/test_agent_nodes.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent_nodes.py` 顶部 import 区补充：

```python
from unittest.mock import patch, MagicMock

from langchain_core.messages import AIMessage

from app.agent.nodes import _build_llm, _resolve_api_key, call_llm
```

（保留原有 `from app.agent.nodes import _build_llm, _resolve_api_key` 一行的合并结果如上。）

文件末尾追加两个测试：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_agent_nodes.py -v`
Expected: 两个新测试 FAIL（`call_llm` 返回的 dict 中没有 `context_usage`）。

- [ ] **Step 3: 实现**

`app/agent/state.py`：在 `confirmed: Optional[bool]` 之前插入一行：

```python
    context_usage: Optional[Dict[str, Any]]      # 最近一次 LLM 调用的 token 用量
```

`app/agent/nodes.py`：

1. 把第 6 行的 `from typing import Literal, Optional` 改为：

```python
from typing import Any, Dict, Literal, Optional
```

2. 在 `call_llm` 函数之前插入辅助函数：

```python
def _extract_context_usage(response: Any) -> Optional[Dict[str, int]]:
    """从 AIMessage.usage_metadata 提取 token 用量；缺失时返回 None。"""
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
```

3. 把 `call_llm` 整体替换为：

```python
def call_llm(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """调用 LLM，绑定工具后生成回复。"""
    api_key = _resolve_api_key(state, config)
    llm = _build_llm(api_key, state, config)
    tools = build_tools(state["project_path"], llm)
    model_with_tools = llm.bind_tools(list(tools.values()), parallel_tool_calls=False)
    response = model_with_tools.invoke(state["messages"])
    updates: dict = {"messages": [response]}
    usage = _extract_context_usage(response)
    if usage is not None:
        updates["context_usage"] = usage
    return updates
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_agent_nodes.py -v`
Expected: 全部 PASS（含原有 12 个测试）。

- [ ] **Step 5: Commit**

```bash
git add app/agent/state.py app/agent/nodes.py tests/test_agent_nodes.py
git commit -m "feat(agent): call_llm 记录 LLM token 用量到 state"
```

---

### Task 2: 后端——_sync_payload 下发 context_usage 与 context_window

**Files:**
- Modify: `app/api/agent.py`（新增窗口映射 + `_sync_payload` 两个字段）
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_agent.py` 末尾追加：

```python
def test_sync_payload_includes_context_usage():
    """_sync_payload 必须返回上下文用量与窗口大小，供前端渲染用量指示。"""
    from app.api.agent import _sync_payload

    values = {
        "messages": [],
        "model": "deepseek-v4-pro",
        "context_usage": {"input_tokens": 1234, "output_tokens": 56, "total_tokens": 1290},
    }

    payload = _sync_payload(values, running=False)

    assert payload["context_usage"]["input_tokens"] == 1234
    assert payload["context_window"] == 1_000_000


def test_sync_payload_context_usage_defaults():
    """无用量数据时返回 None；未知模型窗口默认 1M。"""
    from app.api.agent import _sync_payload

    payload = _sync_payload({}, running=False)
    assert payload["context_usage"] is None
    assert payload["context_window"] == 1_000_000

    payload_unknown = _sync_payload({"model": "some-other-model"}, running=False)
    assert payload_unknown["context_usage"] is None
    assert payload_unknown["context_window"] == 1_000_000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -k context_usage -v`
Expected: 两个新测试 FAIL（KeyError: 'context_usage'）。

- [ ] **Step 3: 实现**

`app/api/agent.py`：

1. 在 `_sync_payload` 函数定义（第 131 行）之前插入：

```python
DEFAULT_CONTEXT_WINDOW = 1_000_000
MODEL_CONTEXT_WINDOWS = {
    "deepseek-v4-pro": 1_000_000,
    "deepseek-v4-flash": 1_000_000,
}


def _context_window_for_model(model: Optional[str]) -> int:
    """按模型名查上下文窗口大小，未知模型默认 1M。"""
    return MODEL_CONTEXT_WINDOWS.get(model or "", DEFAULT_CONTEXT_WINDOW)
```

（确认文件顶部已 import Optional——`app/api/agent.py` 已使用 `Optional[Dict[str, Any]]` 注解，已有该 import，无需新增。）

2. 在 `_sync_payload` 的 return dict 中，`"running": running,` 一行之前插入两行：

```python
        "context_usage": values.get("context_usage"),
        "context_window": _context_window_for_model(values.get("model")),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat(api): 状态快照下发上下文用量与窗口大小"
```

---

### Task 3: 前端——类型、store 与 AgentChat badge

**Files:**
- Modify: `frontend/src/api/agent.ts`（`ContextUsage` 类型 + `AgentState` 两个字段）
- Modify: `frontend/src/stores/agent.ts`（`contextUsage` / `contextWindow` ref）
- Modify: `frontend/src/components/AgentChat.vue`（输入区 badge）
- Test: `frontend/src/components/__tests__/AgentChat.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/components/__tests__/AgentChat.spec.ts` 的 `describe('AgentChat', ...)` 块内末尾（最后一个 `it` 之后）追加：

```ts
  it('shows context usage badge with formatted tokens and percentage', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.contextUsage = { input_tokens: 12345, output_tokens: 100, total_tokens: 12445 }
    agentStore.contextWindow = 1_000_000

    const wrapper = setupWrapper()
    await flushPromises()

    const badge = wrapper.find('.context-usage')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('12.3k/1M · 1.2%')
  })

  it('shows -- when no context usage data yet', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.context-usage').text()).toContain('--')
  })

  it('highlights the badge at 80% and 95% thresholds', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.contextWindow = 1_000_000
    agentStore.contextUsage = { input_tokens: 800_000, output_tokens: 0, total_tokens: 800_000 }

    const wrapper = setupWrapper()
    await flushPromises()
    expect(wrapper.find('.context-usage').classes()).toContain('context-usage--warning')

    agentStore.contextUsage = { input_tokens: 950_000, output_tokens: 0, total_tokens: 950_000 }
    await flushPromises()
    expect(wrapper.find('.context-usage').classes()).toContain('context-usage--danger')
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/components/__tests__/AgentChat.spec.ts`
Expected: 3 个新测试 FAIL（`.context-usage` 不存在；同时 TS 报 `contextUsage` 不存在于 store——vitest 运行时不做类型检查，表现为断言失败即可）。

- [ ] **Step 3: 实现——api 类型**

`frontend/src/api/agent.ts`：在 `AgentMessage` interface 之后插入：

```ts
export interface ContextUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}
```

在 `AgentState` interface 中 `radiomics_progress?: RadiomicsProgress | null` 一行之后插入两行：

```ts
  context_usage?: ContextUsage | null
  context_window?: number
```

- [ ] **Step 4: 实现——store**

`frontend/src/stores/agent.ts`：

1. import 类型列表中追加 `ContextUsage`（与 `RadiomicsProgress` 等同处，按字母序放在 `AgentState` 之后）：

```ts
import type {
  AgentState,
  AgentMessage,
  ContextUsage,
  PendingPlan,
  PendingCommand,
  PendingScript,
  PendingRadiomicsPlan,
  PendingRadiomicsExecution,
  PendingRadiomicsAnalysis,
  RadiomicsProgress,
  ThreadSummary,
} from '@/api/agent'
```

2. 在 `const radiomicsProgress = ref<RadiomicsProgress | null>(null)` 之后插入：

```ts
  // 最近一次 LLM 调用的 token 用量与模型上下文窗口（null 表示尚无数据）。
  const contextUsage = ref<ContextUsage | null>(null)
  const contextWindow = ref<number | null>(null)
```

3. 在 `applyState` 中 `if (state.radiomics_progress !== undefined) { ... }` 块之后插入：

```ts
    if (state.context_usage !== undefined) {
      contextUsage.value = state.context_usage
    }
    if (state.context_window !== undefined) {
      contextWindow.value = state.context_window
    }
```

4. 在 `resetInternalState` 中 `radiomicsProgress.value = null` 之后插入：

```ts
    contextUsage.value = null
    contextWindow.value = null
```

5. 在 store 的 return 对象中 `radiomicsProgress,` 之后插入：

```ts
    contextUsage,
    contextWindow,
```

- [ ] **Step 5: 实现——AgentChat.vue badge**

`frontend/src/components/AgentChat.vue`：

1. 模板：在 `.message-input-area` 内、发送/停止按钮（`<el-button v-if="agentStore.busy"`）之前插入：

```vue
        <el-tooltip :content="contextTooltip" placement="top">
          <span class="context-usage" :class="contextUsageLevel">
            <el-icon><Odometer /></el-icon>
            <span>{{ contextUsageText }}</span>
          </span>
        </el-tooltip>
```

2. 脚本：把 icons import 行改为：

```ts
import { Loading, CircleClose, Promotion, Odometer } from '@element-plus/icons-vue'
```

3. 脚本：在 `statusText` computed 之后插入：

```ts
/** 格式化 token 数：>=1000 用 k，>=1M 用 M。 */
function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    return `${parseFloat((n / 1_000_000).toFixed(2))}M`
  }
  if (n >= 1_000) {
    return `${parseFloat((n / 1_000).toFixed(1))}k`
  }
  return String(n)
}

/** badge 文案：当前上下文用量/窗口 · 百分比；无数据显示 --。 */
const contextUsageText = computed(() => {
  const usage = agentStore.contextUsage
  const window = agentStore.contextWindow
  if (!usage || !window) return '--'
  const pct = ((usage.input_tokens / window) * 100).toFixed(1)
  return `${formatTokens(usage.input_tokens)}/${formatTokens(window)} · ${pct}%`
})

/** 用量阈值样式：>=80% 橙色，>=95% 红色。 */
const contextUsageLevel = computed(() => {
  const usage = agentStore.contextUsage
  const window = agentStore.contextWindow
  if (!usage || !window) return ''
  const ratio = usage.input_tokens / window
  if (ratio >= 0.95) return 'context-usage--danger'
  if (ratio >= 0.8) return 'context-usage--warning'
  return ''
})

/** 悬停 tooltip：精确 token 明细。 */
const contextTooltip = computed(() => {
  const usage = agentStore.contextUsage
  if (!usage) return '发送首条消息后显示上下文用量'
  return (
    `输入 ${usage.input_tokens.toLocaleString()} / ` +
    `输出 ${usage.output_tokens.toLocaleString()} / ` +
    `合计 ${usage.total_tokens.toLocaleString()} tokens`
  )
})
```

4. 样式：在 `<style scoped>` 内 `.model-selector` 规则之后追加：

```css
.context-usage {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: #909399;
  white-space: nowrap;
  margin-bottom: 1px;
  cursor: default;
}

.context-usage--warning {
  color: #e6a23c;
}

.context-usage--danger {
  color: #f56c6c;
}
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/components/__tests__/AgentChat.spec.ts`
Expected: 全部 PASS（含原有 18 个测试）。

- [ ] **Step 7: 类型检查与 lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 无错误。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/agent.ts frontend/src/stores/agent.ts frontend/src/components/AgentChat.vue frontend/src/components/__tests__/AgentChat.spec.ts
git commit -m "feat(frontend): 对话框右下角显示上下文用量 badge"
```

---

### Task 4: 全量回归

**Files:** 无（仅运行验证）

- [ ] **Step 1: 后端全量测试**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 全部 PASS。

- [ ] **Step 2: 前端全量测试**

Run: `cd frontend && npx vitest run`
Expected: 全部 PASS。

- [ ] **Step 3: 前端生产构建**

Run: `cd frontend && npm run build`
Expected: 构建成功（`vue-tsc` 类型检查 + vite build 均无错误）。

- [ ] **Step 4: 人工冒烟（可选，需真实 API key）**

启动后端与前端 dev server，在 Agent 对话框发送一条消息，确认右下角 badge 从 `--` 变为实际用量（如 `3.2k/1M · 0.3%`），悬停显示输入/输出/合计明细。
