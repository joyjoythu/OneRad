# 项目侧边栏可折叠 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让全局布局中的项目侧边栏可折叠为 40px 窄条，折叠状态经 localStorage 记忆。

**Architecture:** 复用 ThreadList 既有折叠模式（Fold/Expand 图标按钮 + collapsed 类 + v-show + localStorage），内聚在 `frontend/src/App.vue` 实现；ProjectList 组件零改动。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Element Plus + vitest。

**Spec:** `docs/superpowers/specs/2026-07-17-project-sidebar-collapse-design.md`

---

### Task 1: App.vue 侧边栏折叠

**Files:**
- Modify: `frontend/src/App.vue`（模板 10-17 行、script、style）
- Test: `frontend/src/__tests__/App.spec.ts`（新建）

- [ ] **Step 1: 写失败测试**

新建 `frontend/src/__tests__/App.spec.ts`：

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import App from '../App.vue'

const SIDEBAR_COLLAPSED_KEY = 'onerad:app:sidebarCollapsed'

function setupWrapper() {
  return mount(App, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        ProjectList: { template: '<div class="project-list-stub" />' },
        'router-link': { template: '<a><slot /></a>' },
        'router-view': true,
      },
    },
  })
}

describe('App sidebar collapse', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('renders expanded by default', () => {
    const wrapper = setupWrapper()

    expect(wrapper.find('.app-sidebar').classes()).not.toContain('app-sidebar--collapsed')
    expect(
      wrapper.find('[data-testid="sidebar-toggle-collapse"]').attributes('aria-label')
    ).toBe('折叠项目面板')
    expect(wrapper.find('.project-list-stub').isVisible()).toBe(true)
  })

  it('collapses on toggle click and persists state', async () => {
    const wrapper = setupWrapper()
    const toggle = wrapper.find('[data-testid="sidebar-toggle-collapse"]')

    await toggle.trigger('click')

    expect(wrapper.find('.app-sidebar').classes()).toContain('app-sidebar--collapsed')
    expect(toggle.attributes('aria-label')).toBe('展开项目面板')
    expect(wrapper.find('.project-list-stub').isVisible()).toBe(false)
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('true')

    await toggle.trigger('click')

    expect(wrapper.find('.app-sidebar').classes()).not.toContain('app-sidebar--collapsed')
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('false')
  })

  it('restores collapsed state from localStorage', () => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, 'true')

    const wrapper = setupWrapper()

    expect(wrapper.find('.app-sidebar').classes()).toContain('app-sidebar--collapsed')
  })
})
```

注意：jsdom 自带 localStorage，`localStorage.clear()` 即可，无需 mock；`data-testid`/`aria-label` 会透传到 el-button 渲染的原生 button（与 ThreadList 的 `data-testid="thread-list-toggle-collapse"` 同一模式）。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/__tests__/App.spec.ts
```

预期：FAIL —— 找不到 `[data-testid="sidebar-toggle-collapse"]`、无 `.app-sidebar--collapsed` 类。

- [ ] **Step 3: 实现 — 改造 App.vue**

模板 10-17 行（`.app-body` 部分）改为：

```html
    <div class="app-body">
      <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': isSidebarCollapsed }">
        <div class="sidebar-toggle-bar">
          <el-button
            link
            size="small"
            :icon="isSidebarCollapsed ? Expand : Fold"
            :aria-label="isSidebarCollapsed ? '展开项目面板' : '折叠项目面板'"
            data-testid="sidebar-toggle-collapse"
            @click="handleToggleSidebar"
          />
        </div>
        <ProjectList v-show="!isSidebarCollapsed" />
      </aside>
      <main class="app-main">
        <router-view />
      </main>
    </div>
```

`<script setup lang="ts">` 改为：

```typescript
import { ref } from 'vue'
import { Expand, Fold } from '@element-plus/icons-vue'
import ProjectList from '@/components/ProjectList.vue'

const SIDEBAR_COLLAPSED_KEY = 'onerad:app:sidebarCollapsed'

function loadSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveSidebarCollapsed(value: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(value))
  } catch {
    // ignore
  }
}

const isSidebarCollapsed = ref(loadSidebarCollapsed())

function handleToggleSidebar(): void {
  isSidebarCollapsed.value = !isSidebarCollapsed.value
  saveSidebarCollapsed(isSidebarCollapsed.value)
}
```

style 中 `.app-sidebar` 规则改为，并新增折叠相关规则：

```css
.app-sidebar {
  width: 320px;
  border-right: 1px solid #e4e7ed;
  overflow-y: auto;
  transition: width 0.2s ease;
}

.sidebar-toggle-bar {
  display: flex;
  justify-content: flex-end;
  padding: 0.25rem 0.5rem;
}

.app-sidebar--collapsed {
  width: 40px;
}

.app-sidebar--collapsed .sidebar-toggle-bar {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/__tests__/App.spec.ts && npm run type-check && npm run lint
```

预期：3 个用例 PASS；type-check 与 lint 无错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.vue frontend/src/__tests__/App.spec.ts
git commit -m "feat: 项目侧边栏可折叠并记忆状态"
```

### Task 2: 前端全量回归

**Files:** 无代码改动，仅验证。

- [ ] **Step 1: 全量测试 + 构建**

```bash
cd frontend && npm run test:unit && npm run build
```

预期：vitest 全部 PASS（含新 App.spec.ts 3 例）；`vue-tsc` 与 `vite build` 成功。

- [ ] **Step 2: 提交计划文档**

```bash
git add docs/superpowers/plans/2026-07-17-project-sidebar-collapse.md
git commit -m "docs: 新增项目侧边栏折叠的实现计划"
```
