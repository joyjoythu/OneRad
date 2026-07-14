# 历史会话面板可折叠实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `/agent` 页面左侧的 `ThreadList` 历史会话面板添加折叠/展开功能，并持久化折叠状态到 `localStorage`。

**Architecture:** `AgentView` 维护折叠状态并负责 `localStorage` 读写，通过 prop 把状态传给 `ThreadList`；`ThreadList` 在标题栏提供折叠按钮，点击时通过事件通知父组件切换。面板宽度通过 CSS class 过渡动画控制。

**Tech Stack:** Vue 3、Element Plus、Pinia、Vitest

---

## 文件结构

| 文件 | 用途 |
|------|------|
| `frontend/src/components/ThreadList.vue` | 新增 `collapsed` prop 与折叠按钮，增加折叠样式 |
| `frontend/src/views/AgentView.vue` | 新增 `localStorage` 读写与折叠状态管理，绑定 prop/event |
| `frontend/src/components/__tests__/ThreadList.spec.ts` | 新增折叠相关组件测试 |
| `frontend/src/views/__tests__/AgentView.spec.ts` | 新增 `localStorage` 持久化测试 |

---

## Task 1: 改造 ThreadList 组件支持折叠

**Files:**
- Modify: `frontend/src/components/ThreadList.vue`
- Test: `frontend/src/components/__tests__/ThreadList.spec.ts`

- [ ] **Step 1: 新增 `collapsed` prop 与 `toggle-collapse` emit**

把 `defineProps` 和 `defineEmits` 改为：

```typescript
defineProps<{
  threads: ThreadSummary[]
  currentThreadId: string | null
  collapsed?: boolean
}>()

const emit = defineEmits<{
  select: [threadId: string]
  create: []
  rename: [threadId: string, title: string]
  delete: [threadId: string]
  'toggle-collapse': []
}>()
```

- [ ] **Step 2: 导入折叠图标并新增折叠按钮**

在图标导入处加入 `Fold` 和 `Expand`：

```typescript
import {
  Plus,
  Edit,
  Delete,
  ChatDotRound,
  Fold,
  Expand,
} from '@element-plus/icons-vue'
```

在 `thread-list-header` 内最前面新增折叠/展开按钮：

```vue
    <div class="thread-list-header">
      <el-button
        link
        size="small"
        :icon="collapsed ? Expand : Fold"
        aria-label="折叠/展开历史会话面板"
        @click="emit('toggle-collapse')"
      />
      <span v-show="!collapsed" class="thread-list-title">历史会话</span>
      <el-button
        v-show="!collapsed"
        type="primary"
        size="small"
        :icon="Plus"
        @click="handleCreate"
      >
        新建对话
      </el-button>
    </div>
```

- [ ] **Step 3: 为列表和空状态添加折叠显隐**

把列表和空状态容器包进 `v-show="!collapsed"`：

```vue
    <div v-show="!collapsed">
      <div v-if="threads.length === 0" class="thread-list-empty">
        <el-empty description="暂无历史会话" :image-size="60" />
      </div>

      <ul v-else class="thread-list-items">
        ...
      </ul>
    </div>
```

- [ ] **Step 4: 新增折叠样式与过渡动画**

在 `<style scoped>` 中修改/新增：

```css
.thread-list {
  display: flex;
  flex-direction: column;
  width: 240px;
  height: 100%;
  border-right: 1px solid #e4e7ed;
  background-color: #f5f7fa;
  transition: width 0.2s ease;
}

.thread-list--collapsed {
  width: 40px;
  align-items: center;
}

.thread-list--collapsed .thread-list-header {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}
```

并把根元素的 class 改为动态绑定：

```vue
<div
  class="thread-list"
  :class="{ 'thread-list--collapsed': collapsed }"
>
```

- [ ] **Step 5: 编写组件测试**

在 `frontend/src/components/__tests__/ThreadList.spec.ts` 新增：

```typescript
it('emits toggle-collapse when collapse button is clicked', async () => {
  const wrapper = mount(ThreadList, {
    props: { threads, currentThreadId: null, collapsed: false },
    global: { plugins: [ElementPlus] },
  })
  const buttons = wrapper.findAll('.thread-list-header button')
  // 第一个按钮是折叠按钮
  await buttons[0].trigger('click')
  expect(wrapper.emitted('toggle-collapse')).toBeTruthy()
})

it('hides content when collapsed', () => {
  const wrapper = mount(ThreadList, {
    props: { threads, currentThreadId: null, collapsed: true },
    global: { plugins: [ElementPlus] },
  })
  expect(wrapper.find('.thread-list-title').isVisible()).toBe(false)
  expect(wrapper.find('.thread-list-items').exists()).toBe(false)
  expect(wrapper.classes()).toContain('thread-list--collapsed')
})

it('shows content when expanded', () => {
  const wrapper = mount(ThreadList, {
    props: { threads, currentThreadId: null, collapsed: false },
    global: { plugins: [ElementPlus] },
  })
  expect(wrapper.find('.thread-list-title').isVisible()).toBe(true)
  expect(wrapper.find('.thread-list-items').exists()).toBe(true)
  expect(wrapper.classes()).not.toContain('thread-list--collapsed')
})
```

注意：如果仓库的测试环境里 Element Plus 组件的 `isVisible()` 不可靠，可改用 `.exists()` 或检查内联 `display` 样式。

- [ ] **Step 6: 运行组件测试**

Run:
```bash
cd frontend
npm run test:unit -- src/components/__tests__/ThreadList.spec.ts
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ThreadList.vue frontend/src/components/__tests__/ThreadList.spec.ts
git commit -m "feat(ui): add collapsed prop and toggle button to ThreadList"
```

---

## Task 2: AgentView 管理折叠状态并持久化

**Files:**
- Modify: `frontend/src/views/AgentView.vue`
- Test: `frontend/src/views/__tests__/AgentView.spec.ts`

- [ ] **Step 1: 新增 localStorage 辅助函数与状态**

在 `AgentView.vue` 的 `script setup` 顶部、其他 ref 之前新增：

```typescript
const THREAD_LIST_COLLAPSED_KEY = 'onerad:agent:threadListCollapsed'

function loadThreadListCollapsed(): boolean {
  try {
    return localStorage.getItem(THREAD_LIST_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveThreadListCollapsed(value: boolean): void {
  try {
    localStorage.setItem(THREAD_LIST_COLLAPSED_KEY, String(value))
  } catch {
    // ignore
  }
}
```

在 `selectedModel` ref 之后新增：

```typescript
const isThreadListCollapsed = ref(loadThreadListCollapsed())
```

- [ ] **Step 2: 新增切换事件处理函数**

在 `handleDeleteThread` 之后新增：

```typescript
function handleToggleThreadListCollapse(): void {
  isThreadListCollapsed.value = !isThreadListCollapsed.value
  saveThreadListCollapsed(isThreadListCollapsed.value)
}
```

- [ ] **Step 3: 绑定 prop 与事件**

把模板中的 `ThreadList` 改为：

```vue
      <ThreadList
        :threads="agentStore.threads"
        :current-thread-id="agentStore.currentThread?.id ?? null"
        :collapsed="isThreadListCollapsed"
        @select="handleSelectThread"
        @create="handleCreateThread"
        @rename="handleRenameThread"
        @delete="handleDeleteThread"
        @toggle-collapse="handleToggleThreadListCollapse"
      />
```

- [ ] **Step 4: 编写持久化测试**

在 `frontend/src/views/__tests__/AgentView.spec.ts` 新增：

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

beforeEach(() => {
  localStorage.clear()
})

it('persists thread list collapse state in localStorage', async () => {
  const wrapper = mount(AgentView, {
    global: { plugins: [createPinia(), ElementPlus, router] },
  })

  // 等待项目加载/初始化
  await flushPromises()

  const collapseButton = wrapper.find('.thread-list-header button')
  expect(collapseButton.exists()).toBe(true)

  await collapseButton.trigger('click')
  expect(localStorage.getItem('onerad:agent:threadListCollapsed')).toBe('true')
  expect(wrapper.find('.thread-list').classes()).toContain('thread-list--collapsed')

  await collapseButton.trigger('click')
  expect(localStorage.getItem('onerad:agent:threadListCollapsed')).toBe('false')
  expect(wrapper.find('.thread-list').classes()).not.toContain('thread-list--collapsed')
})
```

注意：
- 如果 `AgentView.spec.ts` 已有 `localStorage` mock，继续使用该 mock。
- 如果项目加载异步导致折叠按钮一开始不存在，可先用 `projectStore.selectProject(...)` 选中一个项目再挂载。
- 需要确认测试已导入 `flushPromises`，若没有则从 `@vue/test-utils` 导入。

- [ ] **Step 5: 运行视图测试**

Run:
```bash
cd frontend
npm run test:unit -- src/views/__tests__/AgentView.spec.ts
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/AgentView.vue frontend/src/views/__tests__/AgentView.spec.ts
git commit -m "feat(ui): persist thread list collapse state in AgentView"
```

---

## Task 3: 全量验证与收尾

- [ ] **Step 1: 运行前端全量单元测试**

Run:
```bash
cd frontend
npm run test:unit
```
Expected: PASS（包括 ThreadList 与 AgentView 的新增/更新测试）

- [ ] **Step 2: 运行前端构建**

Run:
```bash
cd frontend
npm run build
```
Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 3: 手动验证（可选）**

1. 启动后端：`python main.py`
2. 启动前端 dev：`cd frontend && npm run dev`
3. 进入 `/agent`，确认面板默认展开。
4. 点击标题栏折叠按钮，确认面板收为窄边，聊天区变宽。
5. 刷新页面，确认面板保持折叠状态。
6. 点击展开按钮，确认面板恢复。

- [ ] **Step 4: Commit（如做了修复）**

```bash
git add .
git commit -m "fix(ui): address collapsible thread list review issues"
```

---

## Self-Review

### Spec Coverage

- [x] 面板可折叠 → Task 1 `collapsed` prop + CSS
- [x] 折叠后只保留窄边 → Task 1 `thread-list--collapsed` 样式
- [x] 按钮在标题栏内 → Task 1 header button
- [x] 状态全局持久化 → Task 2 localStorage helpers
- [x] 刷新保持状态 → Task 2 `loadThreadListCollapsed`
- [x] 聊天区自动占满 → Task 1 宽度过渡 + flex 布局（已有 `.agent-chat-wrapper { flex: 1 }`）
- [x] 单元测试 → Task 1/2 测试步骤

### Placeholder Scan

- 无 TBD/TODO
- 所有代码片段完整可执行
- 所有命令与期望输出明确

### Type Consistency

- `collapsed?: boolean` 与 `isThreadListCollapsed` ref 类型一致
- `toggle-collapse` emit 名称在 ThreadList 与 AgentView 中一致
- `localStorage` key 与设计文档一致：`onerad:agent:threadListCollapsed`

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-14-collapsible-thread-list-plan.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints

Which approach would you like?
