# 聊天输入区一体化容器改造实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AgentChat 输入区改为一体化圆角容器（无边框 textarea + 底部工具栏：自动审批 / 用量 / 模型选择 / 圆形发送按钮）。

**Architecture:** 仅改 `frontend/src/components/AgentChat.vue` 的输入区模板与样式：`.message-input-area` 与独立 `.auto-approve-row` 行合并为 `.input-container`（textarea + `.input-toolbar`）。store、API、事件全部不变。三个按按钮文本查找的测试改为按 `aria-label` 查找。

**Tech Stack:** Vue 3 + Element Plus + TypeScript + Vitest（jsdom）。

**设计文档：** `docs/superpowers/specs/2026-07-18-chat-input-container-design.md`

**通用约定：**
- 所有命令在仓库根目录执行，前端命令写作 `cd frontend && <cmd>`。
- 验证基线：`cd frontend && npm run test:unit`、`npm run type-check`、`npm run lint`、`npm run build`。
- 提交信息遵循仓库现有风格（中文、conventional commits 前缀）。

---

### Task 1: AgentChat 输入区容器化（TDD）

**Files:**
- Modify: `frontend/src/components/AgentChat.vue`（输入区模板 + 样式，script 逻辑不动）
- Test: `frontend/src/components/__tests__/AgentChat.spec.ts`

- [ ] **Step 1: 更新测试（失败先行）**

**1a.** 用例 `emits send-message when clicking the send button` 中，把：

```ts
    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeDefined()
    await sendButton!.trigger('click')
```

替换为：

```ts
    const sendButton = wrapper.find('[aria-label="发送"]')
    expect(sendButton.exists()).toBe(true)
    await sendButton.trigger('click')
```

**1b.** 用例 `shows a stop button while busy and emits stop on click` 中，把：

```ts
    const stopButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('停止'))
    expect(stopButton).toBeDefined()
    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeUndefined()

    await stopButton!.trigger('click')
```

替换为：

```ts
    const stopButton = wrapper.find('[aria-label="停止"]')
    expect(stopButton.exists()).toBe(true)
    expect(wrapper.find('[aria-label="发送"]').exists()).toBe(false)

    await stopButton.trigger('click')
```

**1c.** 用例 `shows the send button and no stop button when idle` 中，把：

```ts
    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeDefined()
    const stopButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('停止'))
    expect(stopButton).toBeUndefined()
```

替换为：

```ts
    expect(wrapper.find('[aria-label="发送"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="停止"]').exists()).toBe(false)
```

**1d.** describe 块末尾新增容器结构用例：

```ts
  it('renders the input area as a unified container with a toolbar', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    const container = wrapper.find('.input-container')
    expect(container.exists()).toBe(true)
    expect(container.find('textarea').exists()).toBe(true)

    const toolbar = container.find('.input-toolbar')
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.find('.auto-approve-row').exists()).toBe(true)
    expect(toolbar.find('.model-selector').exists()).toBe(true)
    expect(toolbar.find('[aria-label="发送"]').exists()).toBe(true)
  })
```

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AgentChat.spec.ts`
Expected: 1a/1b/1c/1d 四个用例 FAIL（aria-label 选择器与 `.input-container` 尚不存在），其余 PASS

- [ ] **Step 2: 修改 `AgentChat.vue` 模板**

把现有的 `.auto-approve-row` 区块（整个 div）与 `.message-input-area` 区块（整个 div）整体替换为：

```html
      <div class="input-container">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          :placeholder="inputPlaceholder"
          aria-label="消息输入"
          :disabled="inputDisabled"
          @keydown="handleKeydown"
        />
        <div class="input-toolbar">
          <div class="auto-approve-row">
            <span class="auto-approve-label">自动审批</span>
            <el-switch
              :model-value="agentStore.autoApprove"
              :disabled="agentStore.autoApproveSyncing"
              size="small"
              aria-label="自动审批"
              @change="handleAutoApproveChange"
            />
          </div>
          <div class="input-toolbar-right">
            <el-tooltip :content="contextTooltip" placement="top">
              <span class="context-usage" :class="contextUsageLevel">
                <el-icon><Odometer /></el-icon>
                <span>{{ contextUsageText }}</span>
              </span>
            </el-tooltip>
            <el-select
              v-model="selectedModel"
              class="model-selector"
              placeholder="模型（仅新会话）"
            >
              <el-option label="DeepSeek-V4 Flash" value="deepseek-v4-flash" />
              <el-option label="DeepSeek-V4 Pro" value="deepseek-v4-pro" />
            </el-select>
            <el-button
              v-if="agentStore.busy"
              circle
              type="danger"
              :icon="CircleClose"
              aria-label="停止"
              @click="handleStop"
            />
            <el-button
              v-else
              circle
              type="primary"
              :icon="Promotion"
              :disabled="!canSend"
              aria-label="发送"
              @click="handleSend"
            />
          </div>
        </div>
      </div>
```

注意：`.chat-status` 区块保持在 `.input-container` 之前不动；script 部分（input/canSend/handleSend/handleStop/handleAutoApproveChange/selectedModel/context* 及图标导入）一律不动。

- [ ] **Step 3: 修改 `AgentChat.vue` 样式**

删除 `.auto-approve-row`、`.message-input-area`、`.message-input-area :deep(.el-textarea)`、`.message-input-area .el-button`、`.model-selector :deep(.el-select__wrapper)` 的旧规则，替换为：

```css
.input-container {
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-lg);
  background-color: var(--app-bg-panel);
  transition: border-color 0.2s;
  /* 容器内输入控件去边框去底色：边框由容器统一提供 */
  --el-input-border-color: transparent;
  --el-input-hover-border-color: transparent;
  --el-input-focus-border-color: transparent;
  --el-input-bg-color: transparent;
  --el-fill-color-blank: transparent;
}

.input-container:focus-within {
  border-color: var(--app-text-muted);
}

.input-container :deep(.el-textarea__inner) {
  padding: 0.75rem 0.75rem 0.25rem;
}

.input-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.25rem 0.75rem 0.5rem;
}

.auto-approve-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--app-text-muted);
  font-size: 0.75rem;
}

.input-toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}

.model-selector {
  width: 150px;
}
```

（`.context-usage`、`.context-usage--warning`、`.context-usage--danger`、`.chat-status` 等其余规则保持不变。）

- [ ] **Step 4: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AgentChat.spec.ts && npm run type-check && npm run lint`
Expected: 全部 PASS（含既有「auto-approve 在 model-selector 之前」的 DOM 顺序用例）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/components/__tests__/AgentChat.spec.ts
git commit -m "style: 输入区改为一体化容器，发送/停止改圆形图标按钮"
```

---

### Task 2: 全量验证与收尾

**Files:** 无代码改动，仅验证与提交计划文档。

- [ ] **Step 1: 全量验证**

Run: `cd frontend && npm run test:unit && npm run type-check && npm run lint && npm run build`
Expected: 全部通过

- [ ] **Step 2: 残留检查**

Run: `cd frontend && grep -n "message-input-area" src/components/AgentChat.vue src/components/__tests__/AgentChat.spec.ts`
Expected: 无输出（旧 class 已完全移除）

- [ ] **Step 3: 提交计划文档**

```bash
git add docs/superpowers/plans/2026-07-18-chat-input-container.md
git commit -m "docs: 新增聊天输入区一体化容器实现计划"
```
