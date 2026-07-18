# Agent 页面审批面板重构设计文档

日期：2026-07-18
状态：已获用户批准
范围：Agent 页面右侧面板与审批交互的布局重构。仅前端组件重组，无 API 变化，不改动 agentStore 的数据流与业务逻辑。

## 1. 背景与目标

当前右侧面板（`.agent-side-panel`）在待审批时承载五个审批面板（内容展示 + 确认/取消按钮混在一起），且面板不可折叠。目标：

- 右侧栏只用于**待审批内容的只读展示**（计划表格、脚本代码、命令参数、文件路径等），整体可折叠
- 审批**操作**（确认/取消/计划编辑）移到聊天区**输入框正上方**的可折叠面板中
- 操作日志保留在右侧栏

## 2. 布局结构

AgentView 工作区保持三列：会话列表 | 聊天列 | 右侧栏。

**聊天列（`AgentChat.vue` 模板内，自上而下）：**
1. 消息列表（`.message-list`）
2. **审批面板 `ApprovalPanel`（新增，可折叠）** —— 仅在存在待审批项时渲染（条件与现状一致：`!busy && interrupt && 对应 pending`）
3. 状态栏 / 自动审批 / 输入区（现状不变）

**右侧栏（`AgentView.vue` 重写该区块）：**
1. 标题栏：「计划 / 文件」+ 折叠按钮；折叠后收成 40px 窄条（与项目侧栏/会话列表同模式），折叠状态持久化到 localStorage（键 `onerad:agent:sidePanelCollapsed`）
2. 内容区：有待审批项时按类型渲染对应的只读展示组件；无待审批项时显示空状态占位（「暂无待审批的计划/文件」）
3. 底部：操作日志 `el-collapse`（现状保留）

## 3. 上方审批面板 `ApprovalPanel.vue`（新建）

- 位置：`AgentChat.vue` 模板中消息列表之后、状态栏之前
- 标题栏：状态点 + 「待确认：{类型名}」+ 折叠图标按钮；点击标题栏任意处切换折叠
- 内容区按 interrupt 类型：
  - `file_plan`：内嵌 `PlanEditor`（可编辑表格）+ 按钮组（添加步骤 / 更新计划 / 确认执行 / 取消）
  - `system_command`：摘要（工具名）+ 确认执行 / 取消
  - `python_script`：摘要（风险等级标签）+ 确认执行 / 取消
  - `radiomics_plan`：摘要（图像/掩膜发现数、配对统计）+ 确认 / 取消
  - `radiomics_execution`：摘要（病例数）+ 确认提取 / 取消
  - `radiomics_analysis`：摘要（特征文件、标签列、匹配数）+ 确认分析 / 取消
- 折叠行为：面板内部 `expanded` ref；watch 当前 interrupt 类型与对应 pending 对象引用，任一变化（即新审批到达）→ `expanded = true`；用户手动折叠只改 ref，同一审批保持用户选择。状态不持久化。
- 操作调用：`agentStore.confirm()` / `cancel()` / `updatePlan()`，与现状一致。

## 4. 组件改动

| 组件 | 改动 |
|---|---|
| `ApprovalPanel.vue` | 新建：统一审批操作面板（见 §3） |
| `PlanPanel.vue` | 拆分：编辑表格与按钮逻辑移入 `PlanEditor.vue`（上方用，去掉 el-card 外壳）；新建 `PlanDisplay.vue`（右侧用，只读计划表格）。原 `PlanPanel.vue` 删除 |
| `CommandPanel.vue` | 移除底部按钮区，改为纯只读展示（右侧用） |
| `ScriptPanel.vue` | 同上 |
| `RadiomicsPanel.vue` | 同上 |
| `AnalysisPanel.vue` | 同上 |
| `AgentChat.vue` | 模板插入 `ApprovalPanel`；样式补充 |
| `AgentView.vue` | 右侧栏重写：标题栏 + 折叠 + 空状态 + 只读展示组件 + 操作日志 |

- 只读展示组件复用现有内容区样式（令牌化已完成），仅去掉交互元素。
- `PlanDisplay.vue` 的只读表格：列（序号/操作/源路径/目标路径/原因）纯文本展示，无输入框、无删除列。
- 视觉沿用现有 `--app-*` 令牌，不引入新颜色。

## 5. 状态与数据流

- `agentStore` 的 `interrupt`、`pendingPlan`、`pendingCommand`、`pendingScript`、`pendingRadiomicsPlan`、`pendingRadiomicsExecution`、`pendingRadiomicsAnalysis`、`busy` 及 `confirm/cancel/updatePlan` 方法全部不变，无 API 变化。
- 折叠状态：`ApprovalPanel` 为组件内 ref（会话级）；右侧栏折叠为 localStorage 持久化（跟随项目侧栏现有 try/catch 容错模式）。

## 6. 错误处理

- 沿用现有模式：store 调用 try/catch（错误由 axios 拦截器统一提示）；localStorage 读写 try/catch 静默降级。无新增异常路径。

## 7. 测试

- 新增 `ApprovalPanel.spec.ts`：按类型渲染对应摘要与按钮、新审批到达自动展开、手动折叠保持、按钮调用 store 对应方法
- 新增 `PlanDisplay.spec.ts`：只读渲染计划项、无输入框/按钮
- 更新 `PlanPanel` 相关测试为 `PlanEditor` 测试（编辑/添加/删除/更新计划逻辑不变）
- 更新 `CommandPanel`/`ScriptPanel`/`RadiomicsPanel`/`AnalysisPanel` 测试：断言内容渲染，移除按钮相关断言
- 更新 `AgentView`/`AgentChat` 测试：右侧栏折叠、空状态、ApprovalPanel 挂载位置
- 全量 `npm run test:unit` + `type-check` + `lint` + `build` 通过

## 8. 非目标（YAGNI）

- 不改动 agentStore、API 层、后端
- 不做右侧栏内容的"最近一次审批回看"（无内容即空状态）
- 不为只读展示组件增加编辑能力
- 不调整会话列表与项目侧栏
