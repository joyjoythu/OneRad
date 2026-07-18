# 聊天输入区一体化容器改造设计文档

日期：2026-07-18
状态：已获用户批准
范围：仅 `frontend/src/components/AgentChat.vue` 的输入区模板与样式。store、API、组件事件（`send-message` / `stop` / `update:model`）完全不变。

## 1. 背景与目标

当前输入区为松散的一行排布（textarea + 模型选择器 + 用量 badge + 矩形发送按钮），「自动审批」开关独占一行，视觉上零碎。目标：改为参照 Kimi 输入框的一体化紧凑容器 —— 圆角容器内上方为无边框输入区，下方为工具栏。

## 2. 布局结构

AgentChat 聊天列自上而下不变：消息列表 → ApprovalPanel → 状态栏 → **输入容器**。

**输入容器 `.input-container`：**
- 样式：`--app-bg-panel` 底、`1px solid var(--app-border-strong)` 边框、`--app-radius-lg` 圆角；`focus-within` 时边框色加深为 `var(--app-text-muted)`
- 上部：无边框 textarea（`el-input type="textarea"`，rows=3，通过 `:deep(.el-textarea__inner)` 去掉边框/阴影/底色，透明背景）
- 下部工具栏 `.input-toolbar`（flex 行，垂直居中）：
  - 左侧：「自动审批」label + 小号 `el-switch`（保留现有 class `auto-approve-row` / `auto-approve-label` 于该分组，DOM 顺序仍在模型选择器之前）
  - 右侧（`margin-left: auto`）：上下文用量 badge（现有 `.context-usage` 逻辑不变）→ 无边框模型选择器（去掉 `el-select__wrapper` 阴影边框，宽度保持 150px）→ 圆形发送按钮

**按钮：**
- 发送：`el-button circle type="primary"`，图标 `Promotion`，`aria-label="发送"`，`disabled` 逻辑不变（`!canSend`）
- 停止（busy 时）：`el-button circle type="danger"`，图标 `CircleClose`，`aria-label="停止"`
- 原矩形文字按钮移除；点击行为与 emit 不变

**移除：** 原独立 `.auto-approve-row` 行（并入工具栏）、原 `.message-input-area` 排布。

## 3. 行为保持不变

- textarea 的 `disabled`（busy / interrupt / 无项目）、`placeholder` 文案、Enter 发送 / Shift+Enter 换行 / IME 合成处理
- 模型选择器 `update:model` emit、用量 badge 阈值变色（80%/95%）
- 自动审批开关的 `handleAutoApproveChange` 与 syncing 禁用态
- 全部样式沿用 `--app-*` 令牌，不引入新颜色

## 4. 错误处理

无新增异常路径（纯布局改造）。

## 5. 测试

- 发送/停止改为纯图标按钮后无文字，以下 3 个用例的选择器由「按按钮文本查找」改为按 `aria-label` 查找：
  - `emits send-message when clicking the send button`
  - `shows a stop button while busy and emits stop on click`
  - `shows the send button and no stop button when idle`
- 「renders auto-approve switch above the model selector」用例不受影响（class 保留、DOM 顺序保持）
- 其余用例不变；全量 `npm run test:unit` + `type-check` + `lint` + `build` 通过

## 6. 非目标（YAGNI）

- 不加附件/「+」按钮等参照图中我们没有的功能
- 不改 ApprovalPanel、状态栏、消息列表
- 不改 store、API、其他组件
