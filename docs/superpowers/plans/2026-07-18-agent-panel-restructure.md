# Agent 页面审批面板重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 审批操作移到聊天区输入框上方的可折叠面板；右侧栏改为只读计划/文件展示（可折叠），操作日志保留在右侧栏。

**Architecture:** 新建统一 `ApprovalPanel.vue`（标题栏 + 按类型摘要/编辑 + 操作按钮，位于 AgentChat 消息列表与输入区之间）；`PlanPanel.vue` 拆为 `PlanEditor.vue`（上方面板内嵌的编辑表格）与 `PlanDisplay.vue`（右侧只读表格）；其余四个面板移除按钮区变纯展示。`AgentView.vue` 右侧栏重写为「标题栏 + 折叠 + 只读展示/空状态 + 操作日志」。store 与 API 完全不动。

**Tech Stack:** Vue 3 + Element Plus + Pinia + TypeScript + Vitest（jsdom）。

**设计文档：** `docs/superpowers/specs/2026-07-18-agent-panel-restructure-design.md`

**通用约定：**
- 所有命令在仓库根目录执行，前端命令写作 `cd frontend && <cmd>`。
- 验证基线：`cd frontend && npm run test:unit`、`npm run type-check`、`npm run lint`。
- 提交信息遵循仓库现有风格（中文、conventional commits 前缀）。
- store 用法参考：`frontend/src/stores/agent.ts`；现有面板写法参考各自组件当前版本。

---

### Task 1: `PlanEditor.vue` 与 `PlanDisplay.vue`（PlanPanel 拆分，TDD）

**Files:**
- Create: `frontend/src/components/PlanEditor.vue`
- Create: `frontend/src/components/PlanDisplay.vue`
- Test: `frontend/src/components/__tests__/PlanEditor.spec.ts`
- Test: `frontend/src/components/__tests__/PlanDisplay.spec.ts`

说明：`PlanPanel.vue` 本任务**不删**（AgentView 仍在引用，Task 5 删除）。PlanEditor = 现 PlanPanel 去掉 el-card 外壳与标题头；PlanDisplay = 全新只读表格。

- [ ] **Step 1: 编写失败测试 `PlanEditor.spec.ts`**

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import PlanEditor from '../PlanEditor.vue'
import { useAgentStore } from '@/stores/agent'

const mockPendingPlan = {
  tool_call_id: 'tc-plan-1',
  plan: [
    { action: 'copy', source: 'a.nii.gz', target: 'b/a.nii.gz', reason: '整理' },
    { action: 'move', source: 'c.csv', target: 'b/c.csv', reason: '归档' },
  ],
}

function setupWrapper() {
  return mount(PlanEditor, { global: { plugins: [ElementPlus] } })
}

describe('PlanEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders editable inputs for each plan item', () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()

    // 2 行 × 4 列（操作/源路径/目标路径/原因）均为输入框
    expect(wrapper.findAll('input').length).toBeGreaterThanOrEqual(8)
    expect(wrapper.text()).toContain('添加步骤')
  })

  it('adds and removes plan items', async () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()

    const addBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('添加步骤'))
    await addBtn!.trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)

    const delBtns = wrapper
      .findAll('button')
      .filter((b) => b.text().includes('删除'))
    await delBtns[0].trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  })

  it('calls updatePlan with the edited plan, and confirm/cancel call the store', async () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan
    const updateSpy = vi.spyOn(store, 'updatePlan').mockResolvedValue(undefined)
    const confirmSpy = vi.spyOn(store, 'confirm').mockResolvedValue(undefined)
    const cancelSpy = vi.spyOn(store, 'cancel').mockResolvedValue(undefined)

    const wrapper = setupWrapper()

    const input = wrapper.find('input')
    await input.setValue('rename')

    const updateBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('更新计划'))
    expect(updateBtn).toBeDefined()
    await updateBtn!.trigger('click')
    expect(updateSpy).toHaveBeenCalledWith({
      tool_call_id: 'tc-plan-1',
      plan: expect.any(Array),
    })

    const confirmBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('确认执行'))
    await confirmBtn!.trigger('click')
    expect(confirmSpy).toHaveBeenCalled()

    const cancelBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '取消')
    await cancelBtn!.trigger('click')
    expect(cancelSpy).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 编写失败测试 `PlanDisplay.spec.ts`**

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import PlanDisplay from '../PlanDisplay.vue'
import { useAgentStore } from '@/stores/agent'

const mockPendingPlan = {
  tool_call_id: 'tc-plan-1',
  plan: [
    { action: 'copy', source: 'a.nii.gz', target: 'b/a.nii.gz', reason: '整理' },
  ],
}

function setupWrapper() {
  return mount(PlanDisplay, { global: { plugins: [ElementPlus] } })
}

describe('PlanDisplay', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders plan items as read-only text without inputs or buttons', () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('copy')
    expect(wrapper.text()).toContain('a.nii.gz')
    expect(wrapper.text()).toContain('整理')
    expect(wrapper.findAll('input')).toHaveLength(0)
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('renders an empty table when there is no pending plan', () => {
    const wrapper = setupWrapper()
    expect(wrapper.find('.plan-display').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
  })
})
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/PlanEditor.spec.ts src/components/__tests__/PlanDisplay.spec.ts`
Expected: FAIL（`Cannot find module '../PlanEditor.vue'` / `'../PlanDisplay.vue'`）

- [ ] **Step 4: 实现 `PlanEditor.vue`**（逻辑与现 PlanPanel 完全一致，仅去掉 el-card 与标题头）

```vue
<template>
  <div class="plan-editor">
    <el-alert
      v-if="dirty"
      type="info"
      :closable="false"
      show-icon
      class="plan-dirty-hint"
    >
      计划已被编辑，确认前请点击“更新计划”同步到后端。
    </el-alert>

    <el-table :data="localPlan" border stripe style="width: 100%">
      <el-table-column label="序号" type="index" width="60" align="center" />
      <el-table-column label="操作" prop="action" min-width="120">
        <template #default="{ row }">
          <el-input v-model="row.action" size="small" placeholder="操作" />
        </template>
      </el-table-column>

      <el-table-column label="源路径" prop="source" min-width="160">
        <template #default="{ row }">
          <el-input v-model="row.source" size="small" placeholder="源路径" />
        </template>
      </el-table-column>

      <el-table-column label="目标路径" prop="target" min-width="160">
        <template #default="{ row }">
          <el-input v-model="row.target" size="small" placeholder="目标路径" />
        </template>
      </el-table-column>

      <el-table-column label="原因" prop="reason" min-width="200">
        <template #default="{ row }">
          <el-input v-model="row.reason" size="small" placeholder="原因" />
        </template>
      </el-table-column>

      <el-table-column label="管理" width="120" align="center">
        <template #default="{ $index }">
          <el-button
            link
            type="danger"
            :icon="Delete"
            @click="removeItem($index)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="plan-actions">
      <el-button type="primary" plain :icon="Plus" @click="addItem">
        添加步骤
      </el-button>
      <el-button
        type="success"
        :icon="Check"
        :disabled="!dirty"
        @click="handleUpdate"
      >
        更新计划
      </el-button>
      <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
        确认执行
      </el-button>
      <el-button :icon="Close" @click="handleCancel">取消</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Check, Plus, Delete, CircleCheck, Close } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import type { PlanItem, PendingPlan } from '@/api/agent'

const agentStore = useAgentStore()

const localPlan = ref<PlanItem[]>([])

const dirty = computed(() => {
  return JSON.stringify(localPlan.value) !== JSON.stringify(agentStore.pendingPlan?.plan ?? [])
})

watch(
  () => agentStore.pendingPlan,
  (pending) => {
    localPlan.value = (pending?.plan ?? []).map((item) => ({ ...item }))
  },
  { immediate: true, deep: true }
)

function addItem(): void {
  localPlan.value.push({
    action: '',
    source: '',
    target: '',
    reason: '',
  })
}

function removeItem(index: number): void {
  localPlan.value.splice(index, 1)
}

async function handleUpdate(): Promise<void> {
  const pending = agentStore.pendingPlan
  if (!pending) return

  const payload: PendingPlan = {
    tool_call_id: pending.tool_call_id,
    plan: localPlan.value,
  }

  try {
    await agentStore.updatePlan(payload)
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

async function handleConfirm(): Promise<void> {
  try {
    await agentStore.confirm()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

async function handleCancel(): Promise<void> {
  try {
    await agentStore.cancel()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
</script>

<style scoped>
.plan-editor {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.plan-dirty-hint {
  margin-bottom: 0;
}

.plan-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}
</style>
```

- [ ] **Step 5: 实现 `PlanDisplay.vue`**（只读）

```vue
<template>
  <div class="plan-display">
    <div class="plan-display-title">文件计划（{{ plan.length }} 步）</div>
    <el-table :data="plan" border stripe style="width: 100%">
      <el-table-column label="序号" type="index" width="60" align="center" />
      <el-table-column label="操作" prop="action" min-width="100" show-overflow-tooltip />
      <el-table-column label="源路径" prop="source" min-width="140" show-overflow-tooltip />
      <el-table-column label="目标路径" prop="target" min-width="140" show-overflow-tooltip />
      <el-table-column label="原因" prop="reason" min-width="160" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAgentStore } from '@/stores/agent'
import type { PlanItem } from '@/api/agent'

const agentStore = useAgentStore()

const plan = computed<PlanItem[]>(() => agentStore.pendingPlan?.plan ?? [])
</script>

<style scoped>
.plan-display {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.plan-display-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
}
</style>
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/PlanEditor.spec.ts src/components/__tests__/PlanDisplay.spec.ts && npm run type-check`
Expected: PASS（5 个用例）

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/PlanEditor.vue frontend/src/components/PlanDisplay.vue frontend/src/components/__tests__/PlanEditor.spec.ts frontend/src/components/__tests__/PlanDisplay.spec.ts
git commit -m "feat: PlanPanel 拆分为 PlanEditor（编辑）与 PlanDisplay（只读）"
```

---

### Task 2: 四个面板只读化（Command/Script/Radiomics/Analysis）

**Files:**
- Modify: `frontend/src/components/CommandPanel.vue`
- Modify: `frontend/src/components/ScriptPanel.vue`
- Modify: `frontend/src/components/RadiomicsPanel.vue`
- Modify: `frontend/src/components/AnalysisPanel.vue`
- Test: `frontend/src/components/__tests__/AnalysisPanel.spec.ts`
- Test: `frontend/src/components/__tests__/RadiomicsPanel.spec.ts`

说明：四个面板移除底部按钮区与相关脚本（`handleConfirm`/`handleCancel`、未再使用的图标导入）及 `.command-actions`/`.script-actions`/`.radiomics-actions`/`.analysis-actions` 样式，变成纯只读展示（el-card 与标题头保留）。ScriptPanel.spec 无按钮断言，无需改动。

- [ ] **Step 1: `CommandPanel.vue` —— 模板删除 `.command-actions` 区块**

删除：

```html
        <div class="command-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认执行
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
```

script 中删除 `handleConfirm`、`handleCancel` 两个函数，`CircleCheck, Close` 图标导入（`computed` 仍需要），style 中删除 `.command-actions` 规则。

- [ ] **Step 2: `ScriptPanel.vue` —— 同样处理**

删除模板中：

```html
        <div class="script-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认执行
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
```

script 中删除 `handleConfirm`、`handleCancel` 与图标导入 `CircleCheck, Close`（保留 `computed`），style 中删除 `.script-actions`。

- [ ] **Step 3: `RadiomicsPanel.vue` —— 删除两处 `.radiomics-actions` 区块（execution 分支与 plan 分支各一处）与对应脚本/样式**

模板删除两个：

```html
        <div class="radiomics-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认提取
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
```

和

```html
        <div class="radiomics-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
```

script 删除 `handleConfirm`、`handleCancel` 与图标导入，style 删除 `.radiomics-actions`。

- [ ] **Step 4: `AnalysisPanel.vue` —— 同样处理**

删除模板 `.analysis-actions` 区块（确认分析/取消按钮）、script 中 `handleConfirm`/`handleCancel` 与图标导入、style 中 `.analysis-actions`。

- [ ] **Step 5: 更新 `AnalysisPanel.spec.ts` —— 删除两个按钮用例，改为「无操作按钮」断言**

将 `it('calls store.confirm when confirm button is clicked', ...)` 与 `it('calls store.cancel when cancel button is clicked', ...)` 两个用例整体替换为：

```ts
  it('renders no action buttons (read-only display)', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsAnalysis = mockAnalysis

    const wrapper = setupWrapper()

    expect(wrapper.findAll('button')).toHaveLength(0)
  })
```

并移除不再使用的 `vi` 导入（`import { describe, it, expect, beforeEach, vi } from 'vitest'` 改为 `import { describe, it, expect, beforeEach } from 'vitest'`）。

- [ ] **Step 6: 更新 `RadiomicsPanel.spec.ts` —— 两个用例去掉按钮部分，新增无按钮断言**

第一个用例改为：

```ts
  it('renders execution details (read-only)', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsExecution = mockExecution

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待执行特征提取')
    expect(wrapper.text()).toContain('病例数')
    expect(wrapper.text()).toContain('2')
    expect(wrapper.text()).toContain('Params_labels.yaml')
    expect(wrapper.text()).toContain('p1: images/p1.nii.gz → masks/p1.nii.gz')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
```

第二个用例改为：

```ts
  it('renders plan summary (read-only)', async () => {
    const store = useAgentStore()
    store.pendingRadiomicsPlan = mockPlan

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认配对计划')
    expect(wrapper.text()).toContain('40 / 40')
    expect(wrapper.text()).toContain('高置信 1')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
```

并移除该文件不再使用的 `vi` 导入。

- [ ] **Step 7: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AnalysisPanel.spec.ts src/components/__tests__/RadiomicsPanel.spec.ts src/components/__tests__/ScriptPanel.spec.ts && npm run type-check`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/CommandPanel.vue frontend/src/components/ScriptPanel.vue frontend/src/components/RadiomicsPanel.vue frontend/src/components/AnalysisPanel.vue frontend/src/components/__tests__/AnalysisPanel.spec.ts frontend/src/components/__tests__/RadiomicsPanel.spec.ts
git commit -m "refactor: 四个确认面板移除操作按钮，改为只读展示"
```

---

### Task 3: `ApprovalPanel.vue`（上方审批操作面板，TDD）

**Files:**
- Create: `frontend/src/components/ApprovalPanel.vue`
- Test: `frontend/src/components/__tests__/ApprovalPanel.spec.ts`

- [ ] **Step 1: 编写失败测试 `ApprovalPanel.spec.ts`**

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import ApprovalPanel from '../ApprovalPanel.vue'
import { useAgentStore } from '@/stores/agent'

const mockPendingPlan = {
  tool_call_id: 'tc-plan-1',
  plan: [{ action: 'copy', source: 'a', target: 'b', reason: 'r' }],
}

const mockCommand = {
  tool_call_id: 'tc-cmd-1',
  _pending_tool: 'run_command',
  args: { cmd: 'ls' },
}

const mockScript = {
  tool_call_id: 'tc-script-1',
  code: "print('hi')",
  risk_level: 'high',
  description: '测试',
}

function setupWrapper() {
  return mount(ApprovalPanel, { global: { plugins: [ElementPlus] } })
}

describe('ApprovalPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders nothing when there is no pending approval', () => {
    const wrapper = setupWrapper()
    expect(wrapper.find('.approval-panel').exists()).toBe(false)
  })

  it('embeds the plan editor for file_plan interrupts', () => {
    const store = useAgentStore()
    store.interrupt = 'file_plan'
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：文件计划')
    expect(wrapper.find('.plan-editor').exists()).toBe(true)
  })

  it('shows a summary and confirm/cancel buttons for system_command', async () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand
    const confirmSpy = vi.spyOn(store, 'confirm').mockResolvedValue(undefined)
    const cancelSpy = vi.spyOn(store, 'cancel').mockResolvedValue(undefined)

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：系统命令')
    expect(wrapper.text()).toContain('工具：run_command')

    const confirmBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('确认执行'))
    await confirmBtn!.trigger('click')
    expect(confirmSpy).toHaveBeenCalled()

    const cancelBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '取消')
    await cancelBtn!.trigger('click')
    expect(cancelSpy).toHaveBeenCalled()
  })

  it('shows the risk level for python_script interrupts', () => {
    const store = useAgentStore()
    store.interrupt = 'python_script'
    store.pendingScript = mockScript

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：Python 脚本')
    expect(wrapper.text()).toContain('风险等级：高')
  })

  it('collapses on header click and re-expands when a new approval arrives', async () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand

    const wrapper = setupWrapper()
    const bodyDisplay = () =>
      (wrapper.find('.approval-body').element as HTMLElement).style.display
    expect(bodyDisplay()).not.toBe('none')

    await wrapper.find('.approval-header').trigger('click')
    expect(bodyDisplay()).toBe('none')

    // 新的审批对象到达 → 自动重新展开
    store.pendingCommand = { ...mockCommand, tool_call_id: 'tc-cmd-2' }
    await wrapper.vm.$nextTick()
    expect(bodyDisplay()).not.toBe('none')
  })

  it('does not render while the agent is busy', () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand
    store.busy = true

    const wrapper = setupWrapper()
    expect(wrapper.find('.approval-panel').exists()).toBe(false)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/ApprovalPanel.spec.ts`
Expected: FAIL（`Cannot find module '../ApprovalPanel.vue'`）

- [ ] **Step 3: 实现 `ApprovalPanel.vue`**

```vue
<template>
  <div v-if="view" class="approval-panel">
    <div
      class="approval-header"
      role="button"
      tabindex="0"
      :aria-expanded="expanded"
      @click="toggle"
      @keydown.enter="toggle"
      @keydown.space.prevent="toggle"
    >
      <span class="approval-dot" />
      <span class="approval-title">待确认：{{ view.label }}</span>
      <el-icon class="approval-toggle">
        <ArrowUp v-if="expanded" />
        <ArrowDown v-else />
      </el-icon>
    </div>
    <div v-show="expanded" class="approval-body">
      <PlanEditor v-if="view.type === 'file_plan'" />
      <template v-else>
        <div class="approval-summary">
          <el-tag
            v-if="view.type === 'python_script'"
            :type="riskTagType"
            size="small"
          >
            风险等级：{{ riskLabel }}
          </el-tag>
          <span>{{ view.summary }}</span>
        </div>
        <div class="approval-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            {{ view.confirmLabel }}
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowUp, ArrowDown, CircleCheck, Close } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import PlanEditor from './PlanEditor.vue'

const agentStore = useAgentStore()

type ApprovalType =
  | 'file_plan'
  | 'system_command'
  | 'python_script'
  | 'radiomics_plan'
  | 'radiomics_execution'
  | 'radiomics_analysis'

interface ApprovalView {
  type: ApprovalType
  label: string
  summary: string
  confirmLabel: string
}

const view = computed<ApprovalView | null>(() => {
  if (agentStore.busy) return null
  switch (agentStore.interrupt) {
    case 'file_plan':
      return agentStore.pendingPlan
        ? { type: 'file_plan', label: '文件计划', summary: '', confirmLabel: '' }
        : null
    case 'system_command':
      return agentStore.pendingCommand
        ? {
            type: 'system_command',
            label: '系统命令',
            summary: `工具：${agentStore.pendingCommand._pending_tool}`,
            confirmLabel: '确认执行',
          }
        : null
    case 'python_script':
      return agentStore.pendingScript
        ? { type: 'python_script', label: 'Python 脚本', summary: '', confirmLabel: '确认执行' }
        : null
    case 'radiomics_plan': {
      const plan = agentStore.pendingRadiomicsPlan
      if (!plan) return null
      const high = plan.pairs?.high?.length ?? 0
      const medium = plan.pairs?.medium?.length ?? 0
      const low = plan.pairs?.low?.length ?? 0
      return {
        type: 'radiomics_plan',
        label: '配对计划',
        summary: `发现 ${plan.images_found ?? 0} 图 / ${plan.masks_found ?? 0} 掩膜，配对 高${high} 中${medium} 低${low}`,
        confirmLabel: '确认',
      }
    }
    case 'radiomics_execution': {
      const execution = agentStore.pendingRadiomicsExecution
      if (!execution) return null
      return {
        type: 'radiomics_execution',
        label: '特征提取',
        summary: `病例数：${execution.n_cases}`,
        confirmLabel: '确认提取',
      }
    }
    case 'radiomics_analysis': {
      const analysis = agentStore.pendingRadiomicsAnalysis
      if (!analysis) return null
      return {
        type: 'radiomics_analysis',
        label: '影像组学分析',
        summary: `特征：${analysis.feature_csv}，标签列：${analysis.label_col}，匹配 ${analysis.n_matched} 例`,
        confirmLabel: '确认分析',
      }
    }
    default:
      return null
  }
})

const riskTagType = computed(() => {
  switch (agentStore.pendingScript?.risk_level) {
    case 'low':
      return 'success' as const
    case 'medium':
      return 'warning' as const
    case 'high':
      return 'danger' as const
    default:
      return 'info' as const
  }
})

const riskLabel = computed(() => {
  switch (agentStore.pendingScript?.risk_level) {
    case 'low':
      return '低'
    case 'medium':
      return '中'
    case 'high':
      return '高'
    default:
      return '未知'
  }
})

const expanded = ref(true)

// 新审批到达（interrupt 类型或任一 pending 对象引用变化）时自动展开；
// 用户手动折叠只改 expanded，同一审批保持折叠状态。
watch(
  () => [
    agentStore.interrupt,
    agentStore.pendingPlan,
    agentStore.pendingCommand,
    agentStore.pendingScript,
    agentStore.pendingRadiomicsPlan,
    agentStore.pendingRadiomicsExecution,
    agentStore.pendingRadiomicsAnalysis,
  ],
  () => {
    expanded.value = true
  }
)

function toggle(): void {
  expanded.value = !expanded.value
}

async function handleConfirm(): Promise<void> {
  try {
    await agentStore.confirm()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

async function handleCancel(): Promise<void> {
  try {
    await agentStore.cancel()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
</script>

<style scoped>
.approval-panel {
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-md);
  background-color: var(--app-bg-panel);
}

.approval-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  user-select: none;
}

.approval-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--app-warning);
  flex-shrink: 0;
}

.approval-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
}

.approval-toggle {
  margin-left: auto;
  color: var(--app-text-muted);
}

.approval-body {
  border-top: 1px solid var(--app-border);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.approval-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
}

.approval-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/ApprovalPanel.spec.ts && npm run type-check`
Expected: PASS（6 个用例）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ApprovalPanel.vue frontend/src/components/__tests__/ApprovalPanel.spec.ts
git commit -m "feat: 新增聊天区上方可折叠审批面板 ApprovalPanel"
```

---

### Task 4: `AgentChat.vue` 接入 ApprovalPanel

**Files:**
- Modify: `frontend/src/components/AgentChat.vue`（模板 + script import + 无需改样式）
- Test: `frontend/src/components/__tests__/AgentChat.spec.ts`

- [ ] **Step 1: 新增 AgentChat 测试用例（失败先行）**

在 `AgentChat.spec.ts` 的 describe 块末尾追加：

```ts
  it('renders the approval panel between the message list and the input area when an interrupt is pending', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.interrupt = 'system_command'
    agentStore.pendingCommand = {
      tool_call_id: 'tc-cmd-1',
      _pending_tool: 'run_command',
      args: { cmd: 'ls' },
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const panel = wrapper.find('.approval-panel')
    expect(panel.exists()).toBe(true)

    const html = wrapper.html()
    expect(html.indexOf('message-list')).toBeLessThan(html.indexOf('approval-panel'))
    expect(html.indexOf('approval-panel')).toBeLessThan(html.indexOf('message-input-area'))
  })
```

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AgentChat.spec.ts`
Expected: 新用例 FAIL（无 `.approval-panel`），其余 PASS

- [ ] **Step 2: 修改 `AgentChat.vue`**

模板：在 `</div>`（`.message-list` 结束）之后、`<div class="chat-status" ...>` 之前插入一行：

```html
      <ApprovalPanel />
```

script import 区加入：

```ts
import ApprovalPanel from './ApprovalPanel.vue'
```

- [ ] **Step 3: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AgentChat.spec.ts && npm run type-check`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/components/__tests__/AgentChat.spec.ts
git commit -m "feat: 聊天区接入审批面板，位于消息列表与输入区之间"
```

---

### Task 5: `AgentView.vue` 右侧栏重写，删除 `PlanPanel.vue`

**Files:**
- Modify: `frontend/src/views/AgentView.vue`（模板右侧栏 + script + 样式）
- Delete: `frontend/src/components/PlanPanel.vue`
- Test: `frontend/src/views/__tests__/AgentView.spec.ts`

- [ ] **Step 1: 新增 AgentView 测试用例（失败先行）**

在 `AgentView.spec.ts` 的 describe 块末尾追加（文件头部无需新增导入，`mockProject`/`setupWrapper` 复用）：

```ts
  it('shows the empty state in the side panel when no approval is pending', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('暂无待审批的计划/文件')
  })

  it('shows the read-only script panel in the side panel for python_script interrupts', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    agentStore.interrupt = 'python_script'
    agentStore.pendingScript = {
      tool_call_id: 'tc-1',
      code: "print('hello')",
      risk_level: 'low',
      description: '打印测试',
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const sidePanel = wrapper.find('.agent-side-panel')
    expect(sidePanel.text()).toContain('待执行 Python 脚本')
    expect(sidePanel.text()).toContain("print('hello')")
  })

  it('collapses the side panel and persists state in localStorage', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    const wrapper = setupWrapper()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="side-panel-toggle"]')
    expect(toggle.exists()).toBe(true)

    await toggle.trigger('click')
    expect(localStorage.getItem('onerad:agent:sidePanelCollapsed')).toBe('true')
    expect(wrapper.find('.agent-side-panel').classes()).toContain(
      'agent-side-panel--collapsed'
    )

    await toggle.trigger('click')
    expect(localStorage.getItem('onerad:agent:sidePanelCollapsed')).toBe('false')
    expect(wrapper.find('.agent-side-panel').classes()).not.toContain(
      'agent-side-panel--collapsed'
    )
  })

  it('restores side panel collapse state from localStorage on mount', async () => {
    localStorage.setItem('onerad:agent:sidePanelCollapsed', 'true')

    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.agent-side-panel').classes()).toContain(
      'agent-side-panel--collapsed'
    )
  })
```

Run: `cd frontend && npm run test:unit -- src/views/__tests__/AgentView.spec.ts`
Expected: 4 个新用例 FAIL（无空状态/无 data-testid），其余 PASS

- [ ] **Step 2: 重写 `AgentView.vue` 模板中右侧栏部分**

把 `.agent-side-panel` 整块（含内部五个面板的 v-if 链与 el-collapse）替换为：

```html
      <div
        class="agent-side-panel"
        :class="{ 'agent-side-panel--collapsed': isSidePanelCollapsed }"
      >
        <div class="side-panel-header">
          <el-button
            link
            size="small"
            :icon="isSidePanelCollapsed ? Expand : Fold"
            :aria-label="isSidePanelCollapsed ? '展开计划文件面板' : '折叠计划文件面板'"
            data-testid="side-panel-toggle"
            @click="handleToggleSidePanel"
          />
          <span v-show="!isSidePanelCollapsed" class="side-panel-title">
            计划 / 文件
          </span>
        </div>
        <template v-if="!isSidePanelCollapsed">
          <div class="side-panel-content">
            <PlanDisplay v-if="showPlan" />
            <CommandPanel v-else-if="showCommand" />
            <ScriptPanel v-else-if="showScript" />
            <RadiomicsPanel v-else-if="showRadiomics" />
            <AnalysisPanel v-else-if="showAnalysis" />
            <div v-else class="side-panel-empty">暂无待审批的计划/文件</div>
          </div>

          <el-collapse v-if="agentStore.operationLog.length > 0">
            <el-collapse-item title="操作日志">
              <div class="operation-log">
                <div
                  v-for="(log, index) in agentStore.operationLog"
                  :key="index"
                  class="operation-log-entry"
                >
                  {{ log }}
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </template>
      </div>
```

- [ ] **Step 3: 修改 `AgentView.vue` script**

- import 区：删除 `import PlanPanel from '@/components/PlanPanel.vue'`，加入：

```ts
import { Expand, Fold } from '@element-plus/icons-vue'
import PlanDisplay from '@/components/PlanDisplay.vue'
```

（`CommandPanel`/`ScriptPanel`/`RadiomicsPanel`/`AnalysisPanel` 导入保留。）

- 在 `isThreadListCollapsed` 相关代码之后加入：

```ts
const SIDE_PANEL_COLLAPSED_KEY = 'onerad:agent:sidePanelCollapsed'

function loadSidePanelCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDE_PANEL_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveSidePanelCollapsed(value: boolean): void {
  try {
    localStorage.setItem(SIDE_PANEL_COLLAPSED_KEY, String(value))
  } catch {
    // ignore
  }
}

const isSidePanelCollapsed = ref(loadSidePanelCollapsed())

function handleToggleSidePanel(): void {
  isSidePanelCollapsed.value = !isSidePanelCollapsed.value
  saveSidePanelCollapsed(isSidePanelCollapsed.value)
}

const showPlan = computed(
  () => !agentStore.busy && agentStore.interrupt === 'file_plan' && agentStore.pendingPlan
)
const showCommand = computed(
  () => !agentStore.busy && agentStore.interrupt === 'system_command' && agentStore.pendingCommand
)
const showScript = computed(
  () => !agentStore.busy && agentStore.interrupt === 'python_script' && agentStore.pendingScript
)
const showRadiomics = computed(
  () =>
    !agentStore.busy &&
    (agentStore.interrupt === 'radiomics_plan' || agentStore.interrupt === 'radiomics_execution') &&
    (agentStore.pendingRadiomicsPlan || agentStore.pendingRadiomicsExecution)
)
const showAnalysis = computed(
  () => !agentStore.busy && agentStore.interrupt === 'radiomics_analysis' && agentStore.pendingRadiomicsAnalysis
)
```

- [ ] **Step 4: 修改 `AgentView.vue` 样式**

`.agent-side-panel` 规则改为：

```css
.agent-side-panel {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
  transition: width 0.2s ease;
}

.agent-side-panel--collapsed {
  width: 40px;
  align-items: center;
}

.side-panel-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.agent-side-panel--collapsed .side-panel-header {
  justify-content: center;
}

.side-panel-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
}

.side-panel-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.side-panel-empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--app-text-muted);
  font-size: 0.875rem;
  border: 1px dashed var(--app-border-strong);
  border-radius: var(--app-radius-md);
}
```

（`.operation-log` 等其余规则保持不变。）

- [ ] **Step 5: 删除 `PlanPanel.vue`**

```bash
git rm frontend/src/components/PlanPanel.vue
```

- [ ] **Step 6: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/views/__tests__/AgentView.spec.ts && npm run type-check`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/AgentView.vue frontend/src/views/__tests__/AgentView.spec.ts
git commit -m "feat: 右侧栏改为只读计划/文件展示，支持折叠与空状态"
```

---

### Task 6: 全量验证与收尾

**Files:** 无新增改动，仅验证与提交计划文档。

- [ ] **Step 1: 全量测试**

Run: `cd frontend && npm run test:unit`
Expected: 全部 PASS

- [ ] **Step 2: 类型检查与 lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 通过（注意：未使用的导入会被 lint 拦下，Task 2/5 删改后必须零告警）

- [ ] **Step 3: 生产构建**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 残留引用检查**

Run: `cd frontend && grep -rn "PlanPanel" src/ ; grep -rn "handleConfirm\|handleCancel" src/components/CommandPanel.vue src/components/ScriptPanel.vue src/components/RadiomicsPanel.vue src/components/AnalysisPanel.vue`
Expected: 第一条无输出（PlanPanel 已无引用）；第二条无输出（四个只读面板无遗留按钮处理函数）

- [ ] **Step 5: 提交计划文档**

```bash
git add docs/superpowers/plans/2026-07-18-agent-panel-restructure.md
git commit -m "docs: 新增审批面板重构实现计划"
```
