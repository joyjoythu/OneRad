# OneRad 前端焕新设计文档

日期：2026-07-18
状态：已获用户批准
范围：前端视觉全面焕新（配色、字体层级、间距、圆角、阴影、布局细节），**不改变任何功能逻辑与组件行为**。

## 1. 背景与目标

当前前端（Vue 3 + Element Plus + Pinia + Vite）使用 Element Plus 默认主题加少量硬编码 scoped 样式，观感简陋。目标：

- 整体改为「深色中性风」（Linear/Vercel 式）：近黑底色、灰色细边框分层、白色文字、纯白强调色
- 支持浅色/深色双主题，深色为默认，切换入口放在设置页
- 零新依赖、组件零重写，仅通过设计令牌（CSS 变量）+ Element Plus 官方暗色主题实现

## 2. 主题系统架构

### 2.1 设计令牌 `frontend/src/styles/tokens.css`（新增）

所有视觉常量定义为 CSS 自定义属性：

- `:root` 定义浅色主题值
- `html.dark` 定义深色主题值（覆盖）
- 同时把 Element Plus 的 `--el-*` 变量（如 `--el-color-primary`、`--el-bg-color`、`--el-border-color`、`--el-text-color-primary`、`--el-border-radius-base` 等）映射到我们的令牌，使 EP 组件自动跟随主题
- 引入 EP 官方暗色变量表 `element-plus/theme-chalk/dark/css-vars.css` 作为组件层兜底（我们只覆盖需要定制的变量）

令牌命名前缀 `--app-`，分组：

- 背景：`--app-bg`（应用底色）、`--app-bg-panel`（面板/卡片）、`--app-bg-hover`（悬浮/激活）、`--app-bg-bubble`（用户气泡）
- 边框：`--app-border`（弱）、`--app-border-strong`（强）
- 文字：`--app-text`（主）、`--app-text-secondary`（次）、`--app-text-muted`（弱）
- 强调：`--app-accent`（深色=纯白 #ededed；浅色=近黑 #1f2328）、`--app-accent-text`（强调底上的文字色，与底色相同）
- 状态：`--app-success`、`--app-warning`、`--app-danger`
- 圆角：`--app-radius-sm`（6px）、`--app-radius-md`（8px）、`--app-radius-lg`（12px）

### 2.2 主题控制 `frontend/src/utils/theme.ts`（新增）

- `initTheme()`：应用启动时调用，读 localStorage `onerad:theme`，缺省为 `'dark'`，据此切换 `<html>` 的 `dark` class
- `setTheme(theme: 'light' | 'dark')`：切换 class 并持久化
- `getTheme()`：返回当前主题
- localStorage 读写沿用项目现有 try/catch 容错模式（参考 `App.vue` 中侧栏折叠状态的实现）
- 不跟随系统 `prefers-color-scheme`：用户明确选择深色默认，保持简单

### 2.3 设置页入口

`SettingsView.vue` 增加「外观」区块：浅色/深色二选一（`el-radio-group` 或等价控件），变更即调用 `setTheme()` 即时生效。

### 2.4 令牌值

| 令牌 | 深色（默认） | 浅色 |
|---|---|---|
| `--app-bg` | `#0a0a0a` | `#fafafa` |
| `--app-bg-panel` | `#111111` | `#ffffff` |
| `--app-bg-hover` | `#1a1a1a` | `#f0f0f0` |
| `--app-bg-bubble` | `#262626` | `#eaeaea` |
| `--app-border` | `#1f1f1f` | `#ececec` |
| `--app-border-strong` | `#2e2e2e` | `#d9d9d9` |
| `--app-text` | `#ededed` | `#1f2328` |
| `--app-text-secondary` | `#a3a3a3` | `#6b6b6b` |
| `--app-text-muted` | `#525252` | `#9b9b9b` |
| `--app-accent` | `#ededed` | `#1f2328` |
| `--app-accent-text` | `#0a0a0a` | `#ffffff` |
| `--app-success` | `#4ade80` | `#16a34a` |
| `--app-warning` | `#fbbf24` | `#d97706` |
| `--app-danger` | `#f87171` | `#dc2626` |

## 3. 视觉语言

- 圆角梯度：6px（标签/小按钮）→ 8px（卡片/输入框）→ 12px（气泡/大面板）
- 深色主题靠边框分层，不使用投影；浅色主题允许轻微投影
- 聊天消息：用户消息右对齐实心气泡（`--app-bg-bubble`）；AI 消息左对齐、无气泡、纯文本（ChatGPT/Claude 式排布）
- 字体沿用系统字体栈，通过字号/字重/颜色三级文字令牌建立层级，不引入 Web 字体

## 4. 组件改造范围（仅样式，不动逻辑）

- `main.ts`：引入 `tokens.css` 与 EP 暗色变量表，调用 `initTheme()`
- `App.vue`：顶栏、导航激活态、侧栏全部改用令牌
- `AgentView.vue`：工作区面板卡片化（边框 + 圆角 + 面板底色），操作日志样式更新
- 其余组件（`AgentChat`、`ThreadList`、`ProjectList`、`PlanPanel`、`CommandPanel`、`ScriptPanel`、`RadiomicsPanel`、`AnalysisPanel`、`AgentAvatar`）：硬编码颜色全部替换为令牌；确认面板的按钮层级（主按钮=强调底、次按钮=描边）
- Element Plus 组件主要依赖 `--el-*` 变量映射自动换装；个别贴合不住的组件允许少量覆盖样式，集中放在 `frontend/src/styles/` 内，不散落在各组件
- `SettingsView.vue`：新增外观区块（见 2.3）

## 5. 错误处理

- localStorage 不可用（隐私模式等）：try/catch 静默回退到默认深色，不影响使用
- 无其他新增异常路径（纯样式改造）

## 6. 测试

- 现有 vitest 组件测试必须全部通过（不改组件行为）
- 为 `theme.ts` 新增单元测试（放在 `frontend/src/utils/__tests__/` 或既有测试目录约定位置）：
  - 默认值为 `dark`
  - `setTheme('light')` 移除 `html.dark`，`setTheme('dark')` 添加
  - 选择持久化到 localStorage，重新 `initTheme()` 后恢复
- `npm run build`（含 `vue-tsc` 类型检查）与 `npm run lint` 通过

## 7. 非目标（YAGNI）

- 不引入 Tailwind、不更换 UI 库
- 不跟随系统主题自动切换
- 不调整路由、状态管理、API 层
- 不重排整体三栏布局结构（项目侧栏 / 会话列表 / 聊天区 / 右侧面板保持不变）
