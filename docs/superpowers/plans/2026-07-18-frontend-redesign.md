# OneRad 前端焕新实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将前端整体改为深色中性风（Linear/Vercel 式），支持浅色/深色双主题切换，仅改样式不改功能逻辑。

**Architecture:** 设计令牌（CSS 变量）定义在 `frontend/src/styles/tokens.css`：`:root` 存浅色值、`html.dark` 存深色值，并把 Element Plus 的 `--el-*` 变量映射到令牌。`frontend/src/utils/theme.ts` 负责读 localStorage（默认 `dark`）并切换 `<html>` 的 `dark` class。设置页提供主题切换入口。所有组件 scoped style 中的硬编码颜色替换为 `var(--app-*)` 令牌。

**Tech Stack:** Vue 3 + Element Plus 2.8（官方 `dark/css-vars.css` 暗色变量表）+ TypeScript + Vitest（jsdom）。

**设计文档：** `docs/superpowers/specs/2026-07-18-frontend-redesign-design.md`

**通用约定：**
- 所有命令在仓库根目录执行，前端命令写作 `cd frontend && <cmd>`。
- 验证基线：`cd frontend && npm run test:unit`（现有测试全绿）、`npm run type-check`、`npm run lint`。
- 纯样式任务没有新逻辑可测，验证方式是：现有测试保持全绿 + 类型检查/ lint 通过 + 提交。
- 提交信息遵循仓库现有风格（中文、conventional commits 前缀）。

---

### Task 1: 主题控制模块 `theme.ts`（TDD）

**Files:**
- Create: `frontend/src/utils/theme.ts`
- Test: `frontend/src/utils/__tests__/theme.spec.ts`

- [ ] **Step 1: 编写失败测试**

创建 `frontend/src/utils/__tests__/theme.spec.ts`：

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { getTheme, setTheme, initTheme } from '../theme'

const THEME_KEY = 'onerad:theme'

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  it('defaults to dark when nothing is stored', () => {
    expect(getTheme()).toBe('dark')
  })

  it('initTheme applies the dark class by default', () => {
    initTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('setTheme(light) removes the dark class and persists the choice', () => {
    setTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem(THEME_KEY)).toBe('light')
  })

  it('setTheme(dark) adds the dark class and persists the choice', () => {
    setTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
  })

  it('initTheme restores a persisted light choice', () => {
    localStorage.setItem(THEME_KEY, 'light')
    initTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test:unit -- src/utils/__tests__/theme.spec.ts`
Expected: FAIL（`Cannot find module '../theme'`）

- [ ] **Step 3: 实现 `theme.ts`**

创建 `frontend/src/utils/theme.ts`：

```ts
export type Theme = 'light' | 'dark'

const THEME_KEY = 'onerad:theme'
const DEFAULT_THEME: Theme = 'dark'

export function getTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function setTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // localStorage 不可用（如隐私模式）时静默失败，主题仍可切换
  }
}

export function initTheme(): void {
  setTheme(getTheme())
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm run test:unit -- src/utils/__tests__/theme.spec.ts`
Expected: PASS（5 个用例）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/theme.ts frontend/src/utils/__tests__/theme.spec.ts
git commit -m "feat: 新增主题控制模块 theme.ts（默认深色，可持久化切换）"
```

---

### Task 2: 设计令牌与全局样式，接入 `main.ts`

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/base.css`
- Modify: `frontend/src/main.ts`

- [ ] **Step 1: 创建 `frontend/src/styles/tokens.css`**

注意：`html.dark` 块中重复声明 `--el-*` 映射是必须的——EP 官方暗色表用字面量定义这些变量，`html.dark`（优先级 0-1-1）才能压过它；由于 `var()` 惰性求值，两处映射表达式相同，仅 `--app-*` 取值不同。

```css
/* OneRad 设计令牌
   :root 存浅色值，html.dark 存深色值。
   Element Plus 的 --el-* 变量映射到 --app-* 令牌，使 EP 组件自动跟随主题。 */

:root {
  color-scheme: light;

  /* 背景 */
  --app-bg: #fafafa;
  --app-bg-panel: #ffffff;
  --app-bg-hover: #f0f0f0;
  --app-bg-bubble: #eaeaea;

  /* 边框 */
  --app-border: #ececec;
  --app-border-strong: #d9d9d9;

  /* 文字 */
  --app-text: #1f2328;
  --app-text-secondary: #6b6b6b;
  --app-text-muted: #9b9b9b;

  /* 强调（浅色主题：近黑底白字） */
  --app-accent: #1f2328;
  --app-accent-text: #ffffff;

  /* 状态 */
  --app-success: #16a34a;
  --app-warning: #d97706;
  --app-danger: #dc2626;

  /* 圆角 */
  --app-radius-sm: 6px;
  --app-radius-md: 8px;
  --app-radius-lg: 12px;

  /* Element Plus 变量映射 */
  --el-color-primary: var(--app-accent);
  --el-color-primary-light-3: #4a5158;
  --el-color-primary-light-5: #7d848c;
  --el-color-primary-light-7: #b0b5ba;
  --el-color-primary-light-8: #cdd1d5;
  --el-color-primary-light-9: #e9ebec;
  --el-color-primary-dark-2: #14171b;
  --el-color-success: var(--app-success);
  --el-color-warning: var(--app-warning);
  --el-color-danger: var(--app-danger);
  --el-color-error: var(--app-danger);
  --el-text-color-primary: var(--app-text);
  --el-text-color-regular: var(--app-text);
  --el-text-color-secondary: var(--app-text-secondary);
  --el-text-color-placeholder: var(--app-text-muted);
  --el-text-color-disabled: var(--app-text-muted);
  --el-bg-color: var(--app-bg-panel);
  --el-bg-color-page: var(--app-bg);
  --el-bg-color-overlay: var(--app-bg-panel);
  --el-border-color: var(--app-border-strong);
  --el-border-color-light: var(--app-border);
  --el-border-color-lighter: var(--app-border);
  --el-border-color-extra-light: var(--app-border);
  --el-border-color-hover: var(--app-text-muted);
  --el-fill-color: var(--app-bg-hover);
  --el-fill-color-light: var(--app-bg-hover);
  --el-fill-color-lighter: var(--app-bg);
  --el-fill-color-extra-light: var(--app-bg);
  --el-fill-color-blank: var(--app-bg-panel);
  --el-border-radius-base: var(--app-radius-md);
  --el-border-radius-small: var(--app-radius-sm);
  --el-border-radius-round: var(--app-radius-lg);
  --el-mask-color: rgba(0, 0, 0, 0.5);
}

html.dark {
  color-scheme: dark;

  /* 背景 */
  --app-bg: #0a0a0a;
  --app-bg-panel: #111111;
  --app-bg-hover: #1a1a1a;
  --app-bg-bubble: #262626;

  /* 边框 */
  --app-border: #1f1f1f;
  --app-border-strong: #2e2e2e;

  /* 文字 */
  --app-text: #ededed;
  --app-text-secondary: #a3a3a3;
  --app-text-muted: #525252;

  /* 强调（深色主题：纯白底黑字） */
  --app-accent: #ededed;
  --app-accent-text: #0a0a0a;

  /* 状态 */
  --app-success: #4ade80;
  --app-warning: #fbbf24;
  --app-danger: #f87171;

  /* Element Plus 变量映射（表达式与 :root 相同，重复声明以压过 EP 暗色表字面量） */
  --el-color-primary: var(--app-accent);
  --el-color-primary-light-3: #ffffff;
  --el-color-primary-light-5: #f7f7f7;
  --el-color-primary-light-7: #efefef;
  --el-color-primary-light-8: #e9e9e9;
  --el-color-primary-light-9: #2a2a2a;
  --el-color-primary-dark-2: #d4d4d4;
  --el-color-success: var(--app-success);
  --el-color-warning: var(--app-warning);
  --el-color-danger: var(--app-danger);
  --el-color-error: var(--app-danger);
  --el-text-color-primary: var(--app-text);
  --el-text-color-regular: var(--app-text);
  --el-text-color-secondary: var(--app-text-secondary);
  --el-text-color-placeholder: var(--app-text-muted);
  --el-text-color-disabled: var(--app-text-muted);
  --el-bg-color: var(--app-bg-panel);
  --el-bg-color-page: var(--app-bg);
  --el-bg-color-overlay: var(--app-bg-panel);
  --el-border-color: var(--app-border-strong);
  --el-border-color-light: var(--app-border);
  --el-border-color-lighter: var(--app-border);
  --el-border-color-extra-light: var(--app-border);
  --el-border-color-hover: var(--app-text-muted);
  --el-fill-color: var(--app-bg-hover);
  --el-fill-color-light: var(--app-bg-hover);
  --el-fill-color-lighter: var(--app-bg);
  --el-fill-color-extra-light: var(--app-bg);
  --el-fill-color-blank: var(--app-bg-panel);
  --el-border-radius-base: var(--app-radius-md);
  --el-border-radius-small: var(--app-radius-sm);
  --el-border-radius-round: var(--app-radius-lg);
  --el-mask-color: rgba(0, 0, 0, 0.7);
}
```

- [ ] **Step 2: 创建 `frontend/src/styles/base.css`**

```css
/* 全局基础样式：元素级默认值与少量 EP 组件打磨。
   所有取值都来自 tokens.css 的令牌，不在此处引入新颜色。 */

html,
body {
  margin: 0;
  padding: 0;
}

body {
  background-color: var(--app-bg);
  color: var(--app-text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial,
    sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* 主按钮：强调色底 + 对比色文字（深主题白按钮黑字，浅主题反之） */
.el-button--primary {
  --el-button-text-color: var(--app-accent-text);
  --el-button-hover-text-color: var(--app-accent-text);
  --el-button-active-text-color: var(--app-accent-text);
  --el-button-hover-bg-color: var(--el-color-primary-light-3);
  --el-button-hover-border-color: var(--el-color-primary-light-3);
  --el-button-active-bg-color: var(--el-color-primary-dark-2);
  --el-button-active-border-color: var(--el-color-primary-dark-2);
}

/* 卡片统一为令牌边框 / 圆角 / 底色 */
.el-card {
  --el-card-border-color: var(--app-border);
  --el-card-border-radius: var(--app-radius-md);
  --el-card-bg-color: var(--app-bg-panel);
}

/* 浅色主题卡片轻微投影；深色主题靠边框分层，不用阴影 */
html:not(.dark) .el-card {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
```

- [ ] **Step 3: 修改 `frontend/src/main.ts` 接入样式与主题初始化**

完整替换为（注意引入顺序：EP 暗色表必须在 tokens.css 之前）：

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/tokens.css'
import './styles/base.css'
import App from './App.vue'
import router from './router'
import { initTheme } from './utils/theme'

initTheme()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
```

- [ ] **Step 4: 验证基线**

Run: `cd frontend && npm run test:unit && npm run type-check && npm run lint`
Expected: 全部通过（此时界面应为深色主题，因为 initTheme 默认加 `dark` class）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/tokens.css frontend/src/styles/base.css frontend/src/main.ts
git commit -m "feat: 引入设计令牌与全局样式，接入 EP 官方暗色主题"
```

---

### Task 3: 应用外壳 `App.vue`

**Files:**
- Modify: `frontend/src/App.vue`（仅 `<style>` 块）

- [ ] **Step 1: 替换 `frontend/src/App.vue` 的整个 `<style scoped>` 块**

顶栏改为横向排列（logo 与导航同行），全部颜色改用令牌：

```css
.onerad-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: var(--app-bg);
  color: var(--app-text);
}

.app-header {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.75rem 1.5rem;
  border-bottom: 1px solid var(--app-border);
  background-color: var(--app-bg);
}

.app-header h1 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--app-text);
}

.app-nav {
  display: flex;
  gap: 1rem;
}

.app-nav a {
  color: var(--app-text-secondary);
  text-decoration: none;
  font-size: 0.9375rem;
  padding: 0.25rem 0;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}

.app-nav a:hover {
  color: var(--app-text);
}

.app-nav a.active {
  color: var(--app-text);
  border-bottom-color: var(--app-accent);
}

.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.app-sidebar {
  width: 320px;
  border-right: 1px solid var(--app-border);
  background-color: var(--app-bg-panel);
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

.app-main {
  flex: 1;
  padding: 1.25rem 1.5rem;
  overflow-y: auto;
}
```

- [ ] **Step 2: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/__tests__/App.spec.ts && npm run type-check`
Expected: PASS（App.spec.ts 只断言 class 与导航文案，不受样式影响）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.vue
git commit -m "style: 应用外壳改用设计令牌，顶栏横向排布"
```

---

### Task 4: 项目侧栏 `ProjectList.vue`

**Files:**
- Modify: `frontend/src/components/ProjectList.vue`（仅 `<style>` 块）

- [ ] **Step 1: 替换 `frontend/src/components/ProjectList.vue` 的整个 `<style scoped>` 块**

列表项改为圆角卡片式（与线程列表一致的中性交互态）：

```css
.project-list {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.project-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--app-border);
}

.project-list-header h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--app-text);
}

.project-skeleton {
  padding: 1rem;
}

.project-items {
  list-style: none;
  margin: 0;
  padding: 0.5rem 0;
  overflow-y: auto;
  flex: 1;
}

.project-items li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  margin: 0 0.5rem;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color 0.2s;
  outline: none;
}

.project-items li:hover {
  background-color: var(--app-bg-hover);
}

.project-items li:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: -2px;
  background-color: var(--app-bg-hover);
}

.project-items li.active {
  background-color: var(--app-bg-hover);
}

.project-items li.active .project-name {
  font-weight: 600;
}

.project-info {
  min-width: 0;
}

.project-name {
  font-weight: 500;
  color: var(--app-text);
}

.project-path {
  font-size: 0.75rem;
  color: var(--app-text-muted);
  margin-top: 0.25rem;
  word-break: break-all;
}
```

- [ ] **Step 2: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/ProjectList.spec.ts && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ProjectList.vue
git commit -m "style: 项目列表改用设计令牌与圆角交互态"
```

---

### Task 5: 会话列表 `ThreadList.vue`

**Files:**
- Modify: `frontend/src/components/ThreadList.vue`（仅 `<style>` 块）

- [ ] **Step 1: 替换 `frontend/src/components/ThreadList.vue` 的整个 `<style scoped>` 块**

```css
.thread-list {
  display: flex;
  flex-direction: column;
  width: 240px;
  height: 100%;
  border-right: 1px solid var(--app-border);
  background-color: var(--app-bg);
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

.thread-list-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.thread-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--app-border);
}

.thread-list-title {
  font-weight: 600;
  color: var(--app-text);
}

.thread-list-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.thread-list-items {
  flex: 1;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 0.5rem 0;
}

.thread-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  margin: 0 0.5rem;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color 0.2s;
}

.thread-item:hover,
.thread-item--active {
  background-color: var(--app-bg-hover);
}

.thread-item-content {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  overflow: hidden;
}

.thread-item-icon {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.thread-item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text);
  font-size: 0.875rem;
}

.thread-item-text {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.thread-item-time {
  font-size: 0.75rem;
  color: var(--app-text-muted);
  white-space: nowrap;
}

.thread-item-actions {
  display: flex;
  gap: 0.25rem;
  opacity: 0;
  transition: opacity 0.2s;
}

.thread-item:hover .thread-item-actions {
  opacity: 1;
}
```

- [ ] **Step 2: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/ThreadList.spec.ts && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ThreadList.vue
git commit -m "style: 会话列表改用设计令牌"
```

---

### Task 6: 聊天区 `AgentChat.vue` 与头像 `AgentAvatar.vue`

**Files:**
- Modify: `frontend/src/components/AgentChat.vue`（仅 `<style>` 块）
- Modify: `frontend/src/components/AgentAvatar.vue`（模板内 SVG 颜色 + `<style>` 块）

- [ ] **Step 1: 替换 `AgentChat.vue` 的整个 `<style scoped>` 块**

要点：用户消息右对齐实心气泡（`--app-bg-bubble`）；AI 消息无气泡纯文本；工具消息保留弱化气泡。

```css
.agent-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 1rem;
}

.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1rem;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background-color: var(--app-bg-panel);
}

.message-row {
  display: flex;
  margin-bottom: 0.75rem;
}

.message-row--user {
  justify-content: flex-end;
}

.message-row--assistant {
  justify-content: flex-start;
}

.message-row--tool {
  justify-content: center;
}

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
  color: var(--app-text-muted);
}

.message-bubble {
  padding: 0.75rem 1rem;
  border-radius: var(--app-radius-lg);
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
}

.message-bubble--user {
  background-color: var(--app-bg-bubble);
  color: var(--app-text);
}

.message-bubble--assistant {
  background-color: transparent;
  color: var(--app-text);
  padding-left: 0;
  padding-right: 0;
}

.message-bubble--tool {
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  padding: 0.5rem 0.75rem;
}

.message-tool-call {
  margin-bottom: 0.25rem;
}

.message-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.message-content--tool.is-collapsed {
  max-height: calc(1.5 * 0.875rem * 10);
  overflow: hidden;
}

.tool-toggle {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.25rem;
}

.chat-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  /* 固定占位高度：状态栏出现/消失不再改变消息列表高度，
     避免贴底滚动时内容被挤压回弹。 */
  height: calc(0.875rem * 1.5 + 0.5rem);
  padding: 0.25rem 0.5rem;
  box-sizing: border-box;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  line-height: 1.5;
}

.chat-status--idle {
  visibility: hidden;
}

.auto-approve-row {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.5rem;
  padding: 0 0.25rem 0.25rem;
  color: var(--app-text-muted);
  font-size: 0.75rem;
}

.message-input-area {
  display: flex;
  align-items: flex-end;
  gap: 0.75rem;
}

.message-input-area :deep(.el-textarea) {
  flex: 1;
}

.message-input-area .el-button {
  margin-bottom: 1px;
}

.model-selector {
  width: 150px;
}

.context-usage {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: var(--app-text-muted);
  white-space: nowrap;
  margin-bottom: 1px;
  cursor: default;
}

.context-usage--warning {
  color: var(--app-warning);
}

.context-usage--danger {
  color: var(--app-danger);
}

.model-selector :deep(.el-select__wrapper) {
  margin-bottom: 1px;
}
```

- [ ] **Step 2: 修改 `AgentAvatar.vue`**

SVG 的 presentation attribute 不支持 `var()`，改用内联 `style`。完整替换模板中的 `<svg>` 与 `<style>`：

```html
<template>
  <div class="agent-avatar" role="img" aria-label="智能体头像">
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <line x1="12" y1="7" x2="12" y2="4.5" style="stroke: var(--app-accent-text)" stroke-width="1.5" />
      <circle cx="12" cy="3.5" r="1.2" style="fill: var(--app-accent-text)" />
      <rect x="4" y="7" width="16" height="12.5" rx="3.5" style="fill: var(--app-accent-text)" />
      <circle cx="9.3" cy="12.5" r="1.5" style="fill: var(--app-accent)" />
      <circle cx="14.7" cy="12.5" r="1.5" style="fill: var(--app-accent)" />
      <line
        x1="9"
        y1="16.3"
        x2="15"
        y2="16.3"
        style="stroke: var(--app-accent)"
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
  background-color: var(--app-accent);
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

- [ ] **Step 3: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AgentChat.spec.ts src/components/__tests__/AgentAvatar.spec.ts && npm run type-check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/components/AgentAvatar.vue
git commit -m "style: 聊天区改为用户气泡+AI纯文本排布，头像改用令牌配色"
```

---

### Task 7: 主视图 `AgentView.vue`

**Files:**
- Modify: `frontend/src/views/AgentView.vue`（仅 `<style>` 块）

- [ ] **Step 1: 替换 `AgentView.vue` 的整个 `<style scoped>` 块**

```css
.agent-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 1rem;
}

.agent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.agent-header h2 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--app-text);
}

.agent-workspace {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 1rem;
}

.agent-chat-wrapper {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.agent-side-panel {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
}

.operation-log {
  max-height: 240px;
  overflow-y: auto;
  padding: 0.75rem 1rem;
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-secondary);
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
}

.operation-log-entry {
  white-space: pre-wrap;
  word-break: break-all;
}

.operation-log-entry + .operation-log-entry {
  margin-top: 0.25rem;
}
```

- [ ] **Step 2: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/views/__tests__/AgentView.spec.ts && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/AgentView.vue
git commit -m "style: 主视图与操作日志改用设计令牌"
```

---

### Task 8: 五个确认面板（Plan/Command/Script/Radiomics/Analysis）

**Files:**
- Modify: `frontend/src/components/PlanPanel.vue`（仅 `<style>` 块）
- Modify: `frontend/src/components/CommandPanel.vue`（仅 `<style>` 块）
- Modify: `frontend/src/components/ScriptPanel.vue`（仅 `<style>` 块）
- Modify: `frontend/src/components/RadiomicsPanel.vue`（仅 `<style>` 块）
- Modify: `frontend/src/components/AnalysisPanel.vue`（仅 `<style>` 块）

说明：`el-card` 的边框/圆角/底色已在 `base.css` 全局统一，这里只清理各组件内的硬编码颜色。`ScriptPanel` 的代码块保留常暗配色（`#1e1e1e`/`#d4d4d4`）——这是刻意的代码编辑器观感，深浅主题下均成立。

- [ ] **Step 1: 替换 `PlanPanel.vue` 的整个 `<style scoped>` 块**

```css
.plan-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.plan-title {
  font-weight: 500;
  color: var(--app-text);
}

.plan-dirty-hint {
  margin-bottom: 1rem;
}

.plan-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 1rem;
  align-items: center;
}
```

- [ ] **Step 2: 替换 `CommandPanel.vue` 的整个 `<style scoped>` 块**

```css
.command-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.command-title {
  font-weight: 500;
  color: var(--app-text);
}

.command-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.command-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.command-label {
  color: var(--app-text-secondary);
  font-size: 0.875rem;
}

.command-tool {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  padding: 0.25rem 0.5rem;
  background-color: var(--app-bg-hover);
  border-radius: var(--app-radius-sm);
  border: 1px solid var(--app-border);
  color: var(--app-text);
}

.command-args-pre {
  margin: 0.5rem 0 0;
  padding: 0.75rem 1rem;
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text);
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  white-space: pre-wrap;
  word-break: break-all;
}

.command-actions {
  display: flex;
  gap: 0.75rem;
}
```

- [ ] **Step 3: 替换 `ScriptPanel.vue` 的整个 `<style scoped>` 块**

```css
.script-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.script-title {
  font-weight: 500;
  color: var(--app-text);
}

.script-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 代码块刻意保持常暗：代码编辑器观感在深浅主题下均成立 */
.script-code {
  margin: 0;
  padding: 1rem;
  background-color: #1e1e1e;
  color: #d4d4d4;
  border-radius: var(--app-radius-md);
  overflow-x: auto;
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.6;
}

.script-code code {
  white-space: pre;
  word-break: normal;
}

.script-explanation {
  padding: 0.75rem 1rem;
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.script-explanation p {
  margin: 0.5rem 0 0;
  color: var(--app-text-secondary);
  line-height: 1.5;
}

.script-section-title {
  font-weight: 500;
  color: var(--app-text);
}

.script-actions {
  display: flex;
  gap: 0.75rem;
}
```

- [ ] **Step 4: 替换 `RadiomicsPanel.vue` 的整个 `<style scoped>` 块**

```css
.radiomics-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.radiomics-title {
  font-weight: 500;
  color: var(--app-text);
}

.radiomics-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.radiomics-summary {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  font-size: 0.875rem;
  color: var(--app-text);
}

.radiomics-label {
  color: var(--app-text-secondary);
  font-size: 0.875rem;
}

.radiomics-code {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.8125rem;
  padding: 0.125rem 0.375rem;
  background-color: var(--app-bg-hover);
  border-radius: var(--app-radius-sm);
  border: 1px solid var(--app-border);
  color: var(--app-text);
  word-break: break-all;
}

.radiomics-pairs-list {
  max-height: 240px;
  overflow-y: auto;
  margin-top: 0.375rem;
  padding: 0.5rem 0.75rem;
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-secondary);
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.75rem;
  line-height: 1.6;
}

.radiomics-pair {
  white-space: pre-wrap;
  word-break: break-all;
}

.radiomics-actions {
  display: flex;
  gap: 0.75rem;
}
```

- [ ] **Step 5: 替换 `AnalysisPanel.vue` 的整个 `<style scoped>` 块**

```css
.analysis-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.analysis-title {
  font-weight: 500;
  color: var(--app-text);
}

.analysis-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.analysis-summary {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  font-size: 0.875rem;
  color: var(--app-text);
}

.analysis-label {
  color: var(--app-text-secondary);
  font-size: 0.875rem;
}

.analysis-code {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.8125rem;
  padding: 0.125rem 0.375rem;
  background-color: var(--app-bg-hover);
  border-radius: var(--app-radius-sm);
  border: 1px solid var(--app-border);
  color: var(--app-text);
  word-break: break-all;
}

.analysis-placeholder {
  color: var(--app-text-muted);
}

.analysis-actions {
  display: flex;
  gap: 0.75rem;
}
```

- [ ] **Step 6: 运行相关测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/components/__tests__/AnalysisPanel.spec.ts src/components/__tests__/RadiomicsPanel.spec.ts src/components/__tests__/ScriptPanel.spec.ts && npm run type-check`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/PlanPanel.vue frontend/src/components/CommandPanel.vue frontend/src/components/ScriptPanel.vue frontend/src/components/RadiomicsPanel.vue frontend/src/components/AnalysisPanel.vue
git commit -m "style: 五个确认面板改用设计令牌"
```

---

### Task 9: 设置页 `SettingsView.vue`：外观切换入口

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`（模板 + script + `<style>` 块）

- [ ] **Step 1: 修改模板**

在 `<header class="settings-header">` 之后、`el-empty` 之前插入「外观」区块（不依赖是否选中项目，始终显示）：

```html
    <div class="settings-section">
      <h3 class="settings-section-title">外观</h3>
      <el-radio-group
        :model-value="currentTheme"
        aria-label="主题外观"
        @change="handleThemeChange"
      >
        <el-radio-button value="dark">深色</el-radio-button>
        <el-radio-button value="light">浅色</el-radio-button>
      </el-radio-group>
    </div>
```

- [ ] **Step 2: 修改 script**

在 `<script setup lang="ts">` 的 import 区加入：

```ts
import { getTheme, setTheme, type Theme } from '@/utils/theme'
```

在 `apiKeyDraft` 声明之后加入：

```ts
const currentTheme = ref<Theme>(getTheme())

function handleThemeChange(value: string | number | boolean): void {
  const theme: Theme = value === 'light' ? 'light' : 'dark'
  currentTheme.value = theme
  setTheme(theme)
}
```

- [ ] **Step 3: 替换 `<style scoped>` 块**

```css
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.settings-header h2 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--app-text);
}

.settings-section-title {
  margin: 0 0 0.75rem;
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--app-text);
}

.settings-form {
  max-width: 560px;
}

.api-key-hint {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  color: var(--app-text-muted);
}
```

- [ ] **Step 4: 运行测试与类型检查**

Run: `cd frontend && npm run test:unit -- src/views/__tests__/SettingsView.spec.ts && npm run type-check`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat: 设置页新增外观区块，支持浅色/深色切换"
```

---

### Task 10: 全量验证与收尾

**Files:** 无新增改动，仅验证。

- [ ] **Step 1: 全量测试**

Run: `cd frontend && npm run test:unit`
Expected: 全部测试 PASS（含新增 theme.spec.ts 5 个用例）

- [ ] **Step 2: 类型检查与 lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 通过

- [ ] **Step 3: 生产构建**

Run: `cd frontend && npm run build`
Expected: 构建成功（含 vue-tsc 类型检查）

- [ ] **Step 4: 人工视觉走查**

Run: `cd frontend && npm run dev`，浏览器打开 dev 地址确认：
- 默认进入深色主题（近黑底、白字、纯白主按钮）
- 设置页切换浅色后全站跟随，localStorage 持久化（刷新后保持）
- 聊天区：用户消息右对齐灰气泡，AI 消息无气泡
- 各确认面板、对话框、表格在两种主题下对比度正常

- [ ] **Step 5: 如有遗留硬编码颜色，全局扫尾**

Run: `cd frontend && grep -rn --include="*.vue" -E "#[0-9a-fA-F]{3,6}\b" src/ | grep -v __tests__`
Expected: 仅允许 `ScriptPanel.vue` 的 `#1e1e1e` / `#d4d4d4`（刻意保留的常暗代码块）与 `tokens.css` 本身；其余命中需替换为令牌后再提交。
