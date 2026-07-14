# 历史会话面板可折叠设计

## 背景

在 `/agent` 视图中，左侧新增的 `ThreadList` 历史会话面板当前固定宽度 240px。用户希望该面板可以折叠收起，以便在屏幕较窄或不需要查看历史会话时，给聊天区留出更多空间。

## 目标

- `ThreadList` 支持折叠/展开。
- 折叠后只保留一条窄边（约 40px），并提供展开按钮。
- 折叠状态全局持久化到 `localStorage`，刷新页面后保持。

## 非目标

- 不实现响应式断点自动折叠（如手机端自动隐藏）。
- 不实现拖拽调整面板宽度。
- 不实现按项目独立记忆折叠状态。

## 方案概述

采用父组件管理状态方案：

- `AgentView` 维护 `isThreadListCollapsed` ref，并负责读写 `localStorage`。
- `ThreadList` 接收 `collapsed` prop，并在标题栏内提供折叠/展开按钮；点击时 emit `toggle-collapse`。
- `AgentView` 监听 `toggle-collapse` 切换状态，`ThreadList` 根据 prop 调整自身宽度与内容显隐。

## 数据流

```
AgentView (isThreadListCollapsed + localStorage)
  │
  ├─ prop :collapsed → ThreadList
  │
  └─ 监听 @toggle-collapse ← ThreadList emit
```

- `localStorage` key: `onerad:agent:threadListCollapsed`
- 默认值：`false`（展开）
- 读取失败或值为非法时回退为 `false`

## UI 设计

### 展开状态（现有）

- 宽度 240px。
- 标题栏显示“历史会话” + “新建对话”按钮。
- 显示完整会话列表。

### 折叠状态

- 宽度 40px。
- 标题栏隐藏文字和“新建对话”按钮，仅保留一个展开按钮（`Expand` 图标）。
- 隐藏会话列表和空状态。
- 展开按钮垂直居中或置于顶部。

### 过渡动画

- 面板宽度变化使用 `transition: width 0.2s ease`。
- 内容显隐可通过 `v-show` 或条件渲染控制；为避免布局抖动，展开按钮始终渲染。

## 组件接口变更

### `ThreadList.vue`

新增 prop 和 emit：

```typescript
defineProps<{
  threads: ThreadSummary[]
  currentThreadId: string | null
  collapsed?: boolean
}>

const emit = defineEmits<{
  select: [threadId: string]
  create: []
  rename: [threadId: string, title: string]
  delete: [threadId: string]
  'toggle-collapse': []
}>()
```

标题栏内新增折叠/展开按钮：

```vue
<el-button
  link
  size="small"
  :icon="collapsed ? Expand : Fold"
  @click="emit('toggle-collapse')"
/>
```

样式：

```css
.thread-list {
  width: 240px;
  transition: width 0.2s ease;
}

.thread-list--collapsed {
  width: 40px;
}
```

### `AgentView.vue`

新增状态管理：

```typescript
const THREAD_LIST_COLLAPSED_KEY = 'onerad:agent:threadListCollapsed'

function loadCollapsedState(): boolean {
  try {
    const raw = localStorage.getItem(THREAD_LIST_COLLAPSED_KEY)
    return raw === 'true'
  } catch {
    return false
  }
}

function saveCollapsedState(value: boolean): void {
  try {
    localStorage.setItem(THREAD_LIST_COLLAPSED_KEY, String(value))
  } catch {
    // ignore
  }
}

const isThreadListCollapsed = ref(loadCollapsedState())

function handleToggleCollapse(): void {
  isThreadListCollapsed.value = !isThreadListCollapsed.value
  saveCollapsedState(isThreadListCollapsed.value)
}
```

模板中绑定：

```vue
<ThreadList
  :threads="agentStore.threads"
  :current-thread-id="agentStore.currentThread?.id ?? null"
  :collapsed="isThreadListCollapsed"
  @select="handleSelectThread"
  @create="handleCreateThread"
  @rename="handleRenameThread"
  @delete="handleDeleteThread"
  @toggle-collapse="handleToggleCollapse"
/>
```

## 测试计划

### 组件测试

- `ThreadList.spec.ts`：
  - 验证折叠按钮存在且点击触发 `toggle-collapse`。
  - 验证 `collapsed=true` 时标题、列表、新建按钮隐藏，展开按钮可见。
  - 验证 `collapsed=false` 时正常显示完整面板。

### 视图测试

- `AgentView.spec.ts`：
  - 验证点击折叠按钮后 `localStorage` 写入 `true`。
  - 验证再次点击后 `localStorage` 写入 `false`。
  - 验证初始化时读取 `localStorage` 并应用对应 class。

## 验收标准

- [ ] 历史会话面板可以折叠为约 40px 的窄边。
- [ ] 折叠/展开按钮位于面板标题栏内。
- [ ] 折叠状态全局持久化到 `localStorage`。
- [ ] 刷新页面后保持上次的折叠状态。
- [ ] 聊天区在面板折叠后自动占满剩余空间。
- [ ] 相关单元测试通过。
