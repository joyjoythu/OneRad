# 默认 Agent 页 + 设置页只留 API 配置 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 默认路由进入 Agent 界面；原分析页改为"设置"页（`/settings`），只保留 API 密钥的录入与保存；删除被砍功能的前端代码。

**Architecture:** 新建精简 `SettingsView.vue`（api_key 单项表单 + 保存走既有 `projectStore.saveConfig` 整对象链路）；路由 `/` 改指 AgentView、`/agent` 重定向到 `/`、新增 `/settings`；删除 AnalysisView/AnalysisForm/LogViewer/runStore/api-runs 及其测试。后端零改动。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Element Plus + vue-router + vitest。

**Spec:** `docs/superpowers/specs/2026-07-17-agent-default-settings-page-design.md`

---

### Task 1: 新建 SettingsView

**Files:**
- Create: `frontend/src/views/SettingsView.vue`
- Test: `frontend/src/views/__tests__/SettingsView.spec.ts`（新建）

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/views/__tests__/SettingsView.spec.ts`：

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import SettingsView from '../SettingsView.vue'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/api/projects'

const mockProject = (): Project => ({
  id: 'proj-1',
  name: '测试项目',
  path: '/tmp/proj-1',
  description: '',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  analysis: {
    image_dir: 'images',
    clinical_path: 'clinical.xlsx',
    output_dir: './outputs',
    modality: 'auto',
    covariates: 'age',
    model: 'logistic',
    analysis_model: 'logistic',
    api_key: 'sk-old',
  },
})

function setupWrapper() {
  return mount(SettingsView, {
    global: { plugins: [ElementPlus] },
  })
}

describe('SettingsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('prompts to select a project when none is selected', () => {
    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('请先选择一个项目')
  })

  it('renders the api key input initialized from currentConfig', () => {
    const store = useProjectStore()
    store.currentProject = mockProject()
    store.currentConfig = { ...mockProject().analysis }

    const wrapper = setupWrapper()

    const input = wrapper.find('input')
    expect((input.element as HTMLInputElement).value).toBe('sk-old')
  })

  it('saves only the api key while keeping other config fields', async () => {
    const store = useProjectStore()
    const project = mockProject()
    store.currentProject = project
    store.currentConfig = { ...project.analysis }
    const saveSpy = vi.spyOn(store, 'saveConfig').mockResolvedValue(project)

    const wrapper = setupWrapper()
    await wrapper.find('input').setValue('sk-new')
    await wrapper.find('[data-testid="settings-save"]').trigger('click')
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledWith('proj-1', {
      ...project.analysis,
      api_key: 'sk-new',
    })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/views/__tests__/SettingsView.spec.ts
```

预期：FAIL —— `../SettingsView.vue` 不存在，导入报错。

- [ ] **Step 3: 实现 SettingsView.vue**

新建 `frontend/src/views/SettingsView.vue`：

```vue
<template>
  <div class="settings-view">
    <header class="settings-header">
      <h2>{{ pageTitle }}</h2>
    </header>

    <el-empty v-if="!projectStore.currentProject" description="请先选择一个项目" />

    <el-form v-else label-width="100px" class="settings-form">
      <el-form-item label="API 密钥">
        <el-input
          v-model="apiKeyDraft"
          show-password
          placeholder="请输入 API 密钥"
        />
        <p class="api-key-hint">API 密钥随项目配置保存，Agent 对话时使用</p>
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          :loading="projectStore.loading"
          data-testid="settings-save"
          @click="handleSave"
        >
          保存
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

const apiKeyDraft = ref(projectStore.currentConfig?.api_key ?? '')

// 切换项目/保存成功后，草稿跟随最新配置
watch(
  () => projectStore.currentConfig?.api_key,
  (value) => {
    apiKeyDraft.value = value ?? ''
  }
)

const pageTitle = computed(() => {
  return projectStore.currentProject
    ? `设置 - ${projectStore.currentProject.name}`
    : '设置'
})

async function handleSave(): Promise<void> {
  if (!projectStore.currentProject || !projectStore.currentConfig) {
    ElMessage.warning('请先选择一个项目')
    return
  }
  try {
    await projectStore.saveConfig(projectStore.currentProject.id, {
      ...projectStore.currentConfig,
      api_key: apiKeyDraft.value,
    })
    ElMessage.success('设置已保存')
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
</script>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.settings-header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.settings-form {
  max-width: 560px;
}

.api-key-hint {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  color: #909399;
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/views/__tests__/SettingsView.spec.ts && npm run type-check
```

预期：3 个用例 PASS；type-check 无错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/SettingsView.vue frontend/src/views/__tests__/SettingsView.spec.ts
git commit -m "feat: 新增设置页，仅保留 API 密钥配置"
```

### Task 2: 路由/导航切换 + 删除分析页相关代码

**Files:**
- Modify: `frontend/src/router/index.ts`（全文件替换）
- Modify: `frontend/src/App.vue:5-8`（导航链接）
- Modify: `frontend/src/__tests__/App.spec.ts`（加导航断言）
- Delete: `frontend/src/views/AnalysisView.vue`
- Delete: `frontend/src/components/AnalysisForm.vue`
- Delete: `frontend/src/components/LogViewer.vue`
- Delete: `frontend/src/stores/run.ts`
- Delete: `frontend/src/api/runs.ts`
- Delete: `frontend/src/components/__tests__/AnalysisForm.spec.ts`
- Delete: `frontend/src/stores/__tests__/run.spec.ts`

- [ ] **Step 1: 写失败测试 — App.spec.ts 加导航断言**

在 `frontend/src/__tests__/App.spec.ts` 的 `describe('App sidebar collapse')` 之后新增一个 describe：

```typescript
describe('App navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('shows Agent and 设置 links, no 分析 link', () => {
    const wrapper = setupWrapper()
    const nav = wrapper.find('.app-nav')

    expect(nav.text()).toContain('Agent')
    expect(nav.text()).toContain('设置')
    expect(nav.text()).not.toContain('分析')
  })
})
```

（`setupWrapper` 复用文件顶部已有的那个；router-link stub 会渲染链接文本。）

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/__tests__/App.spec.ts
```

预期：新用例 FAIL —— 导航中还没有"设置"。

- [ ] **Step 3: 改导航与路由，删除旧文件**

`frontend/src/App.vue` 导航（5-8 行）改为：

```html
      <nav class="app-nav">
        <router-link to="/" exact-active-class="active">Agent</router-link>
        <router-link to="/settings" exact-active-class="active">设置</router-link>
      </nav>
```

`frontend/src/router/index.ts` 全文件替换为：

```typescript
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Agent', component: () => import('@/views/AgentView.vue') },
  { path: '/agent', redirect: '/' },
  { path: '/settings', name: 'Settings', component: () => import('@/views/SettingsView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
```

删除文件：

```bash
git rm frontend/src/views/AnalysisView.vue \
  frontend/src/components/AnalysisForm.vue \
  frontend/src/components/LogViewer.vue \
  frontend/src/stores/run.ts \
  frontend/src/api/runs.ts \
  frontend/src/components/__tests__/AnalysisForm.spec.ts \
  frontend/src/stores/__tests__/run.spec.ts
```

删完后确认无残留引用（应无输出）：

```bash
grep -rn "stores/run\|api/runs\|AnalysisForm\|AnalysisView\|LogViewer" frontend/src/
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npm run test:unit && npm run type-check && npm run lint
```

预期：全部 PASS（App.spec.ts 新用例转绿，被删文件的相关测试随之移除）；type-check 与 lint 无错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/router/index.ts frontend/src/App.vue frontend/src/__tests__/App.spec.ts
git commit -m "feat: 默认进入 Agent 页，分析页精简为设置页"
```

（删除的文件已在 Step 3 用 `git rm` 暂存，一并进入本次提交。）

### Task 3: 全量回归

**Files:** 无代码改动，仅验证。

- [ ] **Step 1: 前端全量测试 + 构建**

```bash
cd frontend && npm run test:unit && npm run build
```

预期：vitest 全部 PASS；`vue-tsc` 与 `vite build` 成功（router 中懒加载路径变化会被 build 验证）。

- [ ] **Step 2: 提交计划文档**

```bash
git add docs/superpowers/plans/2026-07-17-agent-default-settings-page.md
git commit -m "docs: 新增默认 Agent 页与设置页精简的实现计划"
```
