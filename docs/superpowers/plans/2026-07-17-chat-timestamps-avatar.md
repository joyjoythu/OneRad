# 聊天时间戳与 Agent 头像实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 聊天气泡和历史会话列表显示时间（消息时间持久化在后端），assistant 消息显示机器人头像。

**Architecture:** 消息时间戳写入 LangChain 消息的 `additional_kwargs["timestamp"]`（UTC ISO），随 SQLite checkpoint 持久化；用户消息在 `_make_message` 创建时打标，AI/工具消息在运行收敛点由 `_ensure_message_timestamps` 补打并 `aupdate_state` 写回；`_render_messages` 输出 `timestamp` 字段。前端加 `formatMessageTime` 工具函数，`AgentChat.vue` 气泡下方显示时间、assistant 行左侧加 `AgentAvatar` 组件，`ThreadList.vue` 标题下方显示会话更新时间。

**Tech Stack:** FastAPI + LangGraph（AsyncSqliteSaver）+ langchain-core；Vue 3 + Pinia + Element Plus + Vitest。

**规格文档:** `docs/superpowers/specs/2026-07-17-chat-timestamps-avatar-design.md`

---

### Task 1: 后端 `_make_message` 打时间戳 + `_render_messages` 输出

**Files:**
- Modify: `app/api/agent.py`（imports 第 1-5 行；`_render_messages` 第 104-130 行；`_make_message` 第 178-188 行）
- Test: `tests/test_api_agent.py`

- [x] **Step 1: 写失败测试**

`tests/test_api_agent.py` 第 13 行的导入改为：

```python
from app.api.agent import (
    get_agent_graph,
    _unanswered_tool_call_ids,
    _agent_config,
    _make_message,
    _render_messages,
)
```

文件顶部 `import uuid`（第 3 行）后加一行：

```python
from datetime import datetime
```

在 `tests/test_api_agent.py` 末尾追加：

```python
def test_make_message_stamps_timestamp():
    msg = _make_message("user", "hello")
    ts = msg.additional_kwargs.get("timestamp")
    assert ts
    # 合法 ISO 8601，解析不抛异常
    datetime.fromisoformat(ts)


def test_render_messages_includes_timestamp():
    ts = "2026-07-17T04:00:00+00:00"
    msg = HumanMessage(content="hi", additional_kwargs={"timestamp": ts})
    rendered = _render_messages({"messages": [msg]})
    assert rendered[0]["timestamp"] == ts


def test_render_messages_omits_missing_timestamp():
    rendered = _render_messages({"messages": [HumanMessage(content="hi")]})
    assert "timestamp" not in rendered[0]
```

- [x] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api_agent.py::test_make_message_stamps_timestamp tests/test_api_agent.py::test_render_messages_includes_timestamp -v`
Expected: FAIL（`_make_message` 未打标；`_render_messages` 输出无 timestamp 键）

- [x] **Step 3: 实现**

`app/api/agent.py` imports 区域，在 `import uuid`（第 3 行）后加：

```python
from datetime import datetime, timezone
```

在 `_render_messages` 定义之前（约第 103 行）加辅助函数：

```python
def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串，用于消息时间戳。"""
    return datetime.now(timezone.utc).isoformat()
```

`_render_messages` 尾部（第 125-130 行）改为：

```python
        elif isinstance(msg, SystemMessage):
            entry = {"role": "system", "content": _stringify_content(msg.content)}
        else:
            entry = {"role": "unknown", "content": _stringify_content(msg.content)}
        ts = msg.additional_kwargs.get("timestamp")
        if ts:
            entry["timestamp"] = ts
        rendered.append(entry)
    return rendered
```

（dict 消息走第 108-110 行的透传分支，timestamp 若存在已自带，无需处理。）

`_make_message`（第 178-188 行）整体改为：

```python
def _make_message(role: str, content: str) -> BaseMessage:
    kwargs = {"timestamp": _utc_now_iso()}
    if role == "user":
        return HumanMessage(content=content, additional_kwargs=kwargs)
    if role == "assistant":
        return AIMessage(content=content, additional_kwargs=kwargs)
    if role == "system":
        return SystemMessage(content=content, additional_kwargs=kwargs)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported message role: {role}",
    )
```

- [x] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_api_agent.py::test_make_message_stamps_timestamp tests/test_api_agent.py::test_render_messages_includes_timestamp tests/test_api_agent.py::test_render_messages_omits_missing_timestamp -v`
Expected: 3 PASS

- [x] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat: 消息创建时打时间戳并在渲染时输出"
```

---

### Task 2: 后端 `_ensure_message_timestamps` 补打 + 接入运行收尾与 /stop

**Files:**
- Modify: `app/api/agent.py`（新增函数；`_stream_agent` finally 第 251-255 行；`/stop` 端点第 621-640 行）
- Test: `tests/test_api_agent.py`

- [x] **Step 1: 写失败测试**

`tests/test_api_agent.py` 第 13 行的导入再改为（追加 `_ensure_message_timestamps`）：

```python
from app.api.agent import (
    get_agent_graph,
    _unanswered_tool_call_ids,
    _agent_config,
    _make_message,
    _render_messages,
    _ensure_message_timestamps,
)
```

在 `from app.api import create_app`（第 12 行）后加一行：

```python
from app.agent import create_agent_graph
```

在 `tests/test_api_agent.py` 末尾追加：

```python
@pytest.mark.anyio
async def test_ensure_message_timestamps_stamps_missing_and_preserves_existing():
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": f"ts-test-{uuid.uuid4().hex[:8]}"}}
    old_ts = "2026-01-01T00:00:00+00:00"
    stamped = AIMessage(content="old", additional_kwargs={"timestamp": old_ts})
    unstamped = ToolMessage(content="res", tool_call_id="call-1")
    await graph.aupdate_state(config, {"messages": [stamped, unstamped]})

    await _ensure_message_timestamps(graph, config)

    messages = (await graph.aget_state(config)).values["messages"]
    assert messages[0].additional_kwargs["timestamp"] == old_ts
    ts = messages[1].additional_kwargs.get("timestamp")
    assert ts
    datetime.fromisoformat(ts)
```

- [x] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api_agent.py::test_ensure_message_timestamps_stamps_missing_and_preserves_existing -v`
Expected: FAIL（ImportError: `_ensure_message_timestamps` 不存在）

- [x] **Step 3: 实现**

在 `app/api/agent.py` 的 `_make_message` 之后新增：

```python
async def _ensure_message_timestamps(graph, config: Dict[str, Any]) -> None:
    """为 state 中缺少 timestamp 的消息补打当前 UTC 时间并写回 checkpoint。

    AI/工具消息由图内部节点在运行期间产生，无法在创建点逐个打标；
    在运行收尾等收敛点统一补打，保证刷新/重启后历史消息时间仍准确。
    已有 timestamp 的消息不改写。
    """
    try:
        snapshot = await graph.aget_state(config)
    except KeyError:
        return
    messages = snapshot.values.get("messages") or []
    changed = False
    for msg in messages:
        if isinstance(msg, dict):
            continue
        kwargs = getattr(msg, "additional_kwargs", None)
        if kwargs is not None and not kwargs.get("timestamp"):
            kwargs["timestamp"] = _utc_now_iso()
            changed = True
    if changed:
        await graph.aupdate_state(config, {"messages": list(messages)})
```

接入点一——`_stream_agent` 的 `finally`（第 251-255 行）改为：

```python
    finally:
        # 运行收尾（正常/异常/取消）统一补打本轮新消息的时间戳；
        # 补打失败不影响清理。
        with suppress(Exception):
            await _ensure_message_timestamps(graph, config)
        app.state.active_agent_streams.discard(thread_id)
        app.state.pipeline_tasks.discard(task)
        app.state.agent_stream_tasks.pop(thread_id, None)
        agent_runtime.unregister(thread_id)
```

接入点二——`/stop` 端点的 `if missing_ids:` 块（第 623-640 行）改为：

```python
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
        await _ensure_message_timestamps(graph, config)
        snapshot = await graph.aget_state(config)
```

- [x] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_api_agent.py::test_ensure_message_timestamps_stamps_missing_and_preserves_existing -v`
Expected: PASS

再跑整个文件确认无回归：

Run: `pytest tests/test_api_agent.py -v`
Expected: 全部 PASS

- [x] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat: 运行收尾为 AI/工具消息补打持久时间戳"
```

---

### Task 3: 前端 `formatMessageTime` 工具函数 + `AgentMessage.timestamp` 类型

**Files:**
- Create: `frontend/src/utils/time.ts`
- Create: `frontend/src/utils/__tests__/time.spec.ts`
- Modify: `frontend/src/api/agent.ts:12`（`AgentMessage` 接口）

- [x] **Step 1: 写失败测试**

创建 `frontend/src/utils/__tests__/time.spec.ts`：

```ts
import { describe, it, expect } from 'vitest'
import { formatMessageTime } from '../time'

const pad = (n: number): string => String(n).padStart(2, '0')

describe('formatMessageTime', () => {
  it('formats same-day timestamps as HH:MM', () => {
    const now = new Date()
    const iso = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      9,
      5,
    ).toISOString()
    expect(formatMessageTime(iso)).toBe('09:05')
  })

  it('formats older timestamps as MM-DD HH:MM', () => {
    const iso = '2020-03-04T05:06:07+00:00'
    const d = new Date(iso)
    const expected = `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    expect(formatMessageTime(iso)).toBe(expected)
  })

  it('returns empty string for invalid input', () => {
    expect(formatMessageTime('not-a-date')).toBe('')
    expect(formatMessageTime('')).toBe('')
  })
})
```

- [x] **Step 2: 运行测试确认失败**

Run（在 `frontend/` 目录下）: `npx vitest run src/utils/__tests__/time.spec.ts`
Expected: FAIL（`../time` 模块不存在）

- [x] **Step 3: 实现**

创建 `frontend/src/utils/time.ts`：

```ts
const pad = (n: number): string => String(n).padStart(2, '0')

/**
 * 消息/会话时间格式化：UTC ISO 转本地时间。
 * 当天的消息显示 HH:MM，更早的显示 MM-DD HH:MM；无效输入返回空串。
 */
export function formatMessageTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return sameDay ? hm : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`
}
```

`frontend/src/api/agent.ts` 的 `AgentMessage` 接口中，在 `content: string` 一行之后插入一行（其余行保持不变）：

```ts
  timestamp?: string
```

- [x] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/utils/__tests__/time.spec.ts`
Expected: 3 PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/utils/time.ts frontend/src/utils/__tests__/time.spec.ts frontend/src/api/agent.ts
git commit -m "feat(frontend): 消息时间格式化工具与 AgentMessage.timestamp 类型"
```

---

### Task 4: `AgentAvatar` 机器人头像组件

**Files:**
- Create: `frontend/src/components/AgentAvatar.vue`
- Create: `frontend/src/components/__tests__/AgentAvatar.spec.ts`

- [x] **Step 1: 写失败测试**

创建 `frontend/src/components/__tests__/AgentAvatar.spec.ts`：

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentAvatar from '../AgentAvatar.vue'

describe('AgentAvatar', () => {
  it('renders a circular robot avatar', () => {
    const wrapper = mount(AgentAvatar)
    const avatar = wrapper.find('.agent-avatar')
    expect(avatar.exists()).toBe(true)
    expect(avatar.attributes('role')).toBe('img')
    expect(wrapper.find('svg').exists()).toBe(true)
  })
})
```

- [x] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/components/__tests__/AgentAvatar.spec.ts`
Expected: FAIL（组件不存在）

- [x] **Step 3: 实现**

创建 `frontend/src/components/AgentAvatar.vue`：

```vue
<template>
  <div class="agent-avatar" role="img" aria-label="智能体头像">
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <line x1="12" y1="7" x2="12" y2="4.5" stroke="#ffffff" stroke-width="1.5" />
      <circle cx="12" cy="3.5" r="1.2" fill="#ffffff" />
      <rect x="4" y="7" width="16" height="12.5" rx="3.5" fill="#ffffff" />
      <circle cx="9.3" cy="12.5" r="1.5" fill="#409eff" />
      <circle cx="14.7" cy="12.5" r="1.5" fill="#409eff" />
      <line
        x1="9"
        y1="16.3"
        x2="15"
        y2="16.3"
        stroke="#409eff"
        stroke-width="1.5"
        stroke-linecap="round"
      />
    </svg>
  </div>
</template>

<style scoped>
.agent-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: #409eff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-avatar svg {
  width: 22px;
  height: 22px;
}
</style>
```

（Element Plus 图标库没有机器人图标，故用内联 SVG 自绘：蓝底圆 + 白色机器人。）

- [x] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/components/__tests__/AgentAvatar.spec.ts`
Expected: 1 PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/components/AgentAvatar.vue frontend/src/components/__tests__/AgentAvatar.spec.ts
git commit -m "feat(frontend): Agent 机器人头像组件"
```

---

### Task 5: `AgentChat.vue` 显示头像与消息时间

**Files:**
- Modify: `frontend/src/components/AgentChat.vue`（template 第 18-78 行；script imports 第 150-155 行；style 第 387-413 行）
- Test: `frontend/src/components/__tests__/AgentChat.spec.ts`

- [x] **Step 1: 写失败测试**

在 `frontend/src/components/__tests__/AgentChat.spec.ts` 的 `describe('AgentChat')` 内追加：

```ts
  it('shows timestamp only under messages that have one', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    const now = new Date()
    const iso = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      8,
      30,
    ).toISOString()
    agentStore.messages = [
      { role: 'user', content: 'hi', timestamp: iso },
      { role: 'assistant', content: 'hello' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const times = wrapper.findAll('.message-time')
    expect(times).toHaveLength(1)
    expect(times[0].text()).toBe('08:30')
  })

  it('renders avatar for assistant messages only', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.messages = [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'hello' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.findAll('.agent-avatar')).toHaveLength(1)
    const rows = wrapper.findAll('.message-row')
    expect(rows[0].find('.agent-avatar').exists()).toBe(false)
    expect(rows[1].find('.agent-avatar').exists()).toBe(true)
  })
```

- [x] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/components/__tests__/AgentChat.spec.ts`
Expected: 新增 2 个用例 FAIL（`.message-time` / `.agent-avatar` 不存在），其余 PASS

- [x] **Step 3: 实现**

template 中消息循环（第 18-78 行）整体替换为：

```html
        <div
          v-for="(message, index) in agentStore.messages"
          :key="index"
          :class="['message-row', `message-row--${message.role}`]"
        >
          <AgentAvatar
            v-if="message.role === 'assistant'"
            class="message-avatar"
          />
          <div :class="['message-main', `message-main--${message.role}`]">
            <div
              :class="[
                'message-bubble',
                `message-bubble--${message.role}`,
              ]"
            >
              <div
                v-if="message.role === 'tool'"
                class="message-tool-call"
              >
                <el-tag size="small" type="info" effect="plain">
                  工具调用
                </el-tag>
              </div>
              <div
                v-else-if="toolCallNames(message)"
                class="message-tool-call"
              >
                <el-tag size="small" type="warning" effect="plain">
                  调用工具：{{ toolCallNames(message) }}
                </el-tag>
              </div>
              <div
                v-if="message.content"
                class="message-content"
                :class="{
                  'message-content--tool': message.role === 'tool',
                  'is-collapsed':
                    message.role === 'tool' &&
                    isToolCollapsed(index, message.content),
                }"
              >
                {{ message.content }}
              </div>
              <div
                v-if="
                  message.role === 'tool' &&
                  shouldCollapseTool(message.content)
                "
                class="tool-toggle"
              >
                <el-button
                  link
                  size="small"
                  :aria-label="
                    isToolCollapsed(index, message.content)
                      ? '展开工具输出'
                      : '收起工具输出'
                  "
                  @click="toggleTool(index, message.content)"
                >
                  {{ isToolCollapsed(index, message.content) ? '展开' : '收起' }}
                </el-button>
              </div>
            </div>
            <div v-if="message.timestamp" class="message-time">
              {{ formatMessageTime(message.timestamp) }}
            </div>
          </div>
        </div>
```

script imports 区（第 150-155 行，`import type { AgentMessage } from '@/api/agent'` 之后）加两行：

```ts
import AgentAvatar from './AgentAvatar.vue'
import { formatMessageTime } from '@/utils/time'
```

style 调整：

- `.message-bubble`（第 387-394 行）删掉其中的 `max-width: 80%;` 一行，其余不变（宽度约束上移到 `.message-main`）。
- `.message-bubble--tool`（第 407-413 行）删掉其中的 `max-width: 90%;` 一行，其余不变。
- 在 `.message-row--tool` 规则之后新增：

```css
.message-main {
  display: flex;
  flex-direction: column;
  max-width: 80%;
}

.message-main--tool {
  max-width: 90%;
}

.message-main--user {
  align-items: flex-end;
}

.message-main--assistant {
  align-items: flex-start;
}

.message-avatar {
  margin-right: 0.5rem;
  margin-top: 2px;
}

.message-time {
  margin-top: 0.25rem;
  padding: 0 0.25rem;
  font-size: 0.75rem;
  line-height: 1.2;
  color: #909399;
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/components/__tests__/AgentChat.spec.ts`
Expected: 全部 PASS（含原有用例）

- [x] **Step 5: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/components/__tests__/AgentChat.spec.ts
git commit -m "feat(frontend): 聊天气泡显示时间与 Agent 头像"
```

---

### Task 6: `ThreadList.vue` 显示会话更新时间

**Files:**
- Modify: `frontend/src/components/ThreadList.vue`（template 第 40-43 行；script 第 65-81 行；style 第 209-227 行）
- Test: `frontend/src/components/__tests__/ThreadList.spec.ts`

- [x] **Step 1: 写失败测试**

在 `frontend/src/components/__tests__/ThreadList.spec.ts` 的 `describe('ThreadList')` 内追加：

```ts
  it('renders updated time for each thread', () => {
    const wrapper = mountThreadList({ threads, currentThreadId: null })
    const times = wrapper.findAll('.thread-item-time')
    expect(times).toHaveLength(2)
    for (const t of times) {
      expect(t.text()).toMatch(/^\d{2}:\d{2}$|^\d{2}-\d{2} \d{2}:\d{2}$/)
    }
  })
```

（mock 数据 `updated_at` 为 `'2026-01-02'` / `'2026-01-03'`，具体时分秒取决于运行时区，故用正则覆盖两种格式分支；精确格式由 time.spec.ts 保证。）

- [x] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/components/__tests__/ThreadList.spec.ts`
Expected: 新用例 FAIL（`.thread-item-time` 不存在）

- [x] **Step 3: 实现**

template 第 40-43 行 `.thread-item-content` 改为：

```html
          <div class="thread-item-content">
            <el-icon class="thread-item-icon"><ChatDotRound /></el-icon>
            <div class="thread-item-text">
              <span class="thread-item-title">{{ thread.title || '未命名会话' }}</span>
              <span v-if="threadTime(thread)" class="thread-item-time">
                {{ threadTime(thread) }}
              </span>
            </div>
          </div>
```

script 中，`import type { ThreadSummary } from '@/api/agent'`（第 75 行）之后加：

```ts
import { formatMessageTime } from '@/utils/time'

function threadTime(thread: ThreadSummary): string {
  return formatMessageTime(thread.updated_at || thread.created_at)
}
```

style 中，在 `.thread-item-title` 规则之后新增：

```css
.thread-item-text {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.thread-item-time {
  font-size: 0.75rem;
  color: #909399;
  white-space: nowrap;
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/components/__tests__/ThreadList.spec.ts`
Expected: 全部 PASS

- [x] **Step 5: Commit**

```bash
git add frontend/src/components/ThreadList.vue frontend/src/components/__tests__/ThreadList.spec.ts
git commit -m "feat(frontend): 历史会话列表显示更新时间"
```

---

### Task 7: 全量回归

**Files:** 无（仅运行验证）

- [x] **Step 1: 后端测试**

Run: `pytest tests/test_api_agent.py tests/test_agent_graph.py -v`
Expected: 全部 PASS

- [x] **Step 2: 前端全量测试 + 静态检查**

Run（在 `frontend/` 目录下）:

```bash
npm run test:unit
npm run lint
npm run type-check
```

Expected: 全部测试 PASS；lint 无错误；type-check 无错误

- [x] **Step 3: 人工验收清单（启动应用目视确认）**

- 发送一条消息：用户气泡与 AI 回复气泡下方各显示当天时间 `HH:MM`；AI 回复左侧有蓝底机器人头像。
- 停止一次运行：补打的「已取消」工具消息也带时间。
- 刷新页面：历史消息时间仍为原始发送时间，不是刷新时间。
- 左侧会话列表每条标题下方显示更新时间。
