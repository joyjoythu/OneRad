# 右侧计划面板（Todo List）设计

日期：2026-07-21

## 背景与目标

用户通过快捷操作"开始分析"时，主 Agent 按 `skills/radiomics-workflow/SKILL.md` 的宏观流程执行：项目勘察 → 配对发现 → 参数确认 → 特征提取 → 临床核对 → 建模分析 → 解读与报告。目前前端无法直观看到整体进度，只有零散的工具调用和审批面板。

目标：在右侧面板顶部加一个 Todo List 面板，实时展示这 7 个宏观步骤的状态（pending / in_progress / completed），让用户清晰看到当前分析进度。

## 方案：模型自报（update_todo_list 工具）

步骤内容由模型按 skill 流程自己汇报，而非后端硬编码推导。理由：步骤文案贴合上下文；续分析等分支场景由模型判断最准确。

## 后端改动

### 新增 `update_todo_list` 工具（`app/agent/tools.py`）

- 入参：完整列表 `[{content: str, status: "pending" | "in_progress" | "completed"}]`，全量替换语义，模型每次提交整个列表。
- 约定同一时刻至多一个 `in_progress`；后端不强制校验，仅透传。
- 无需人工审批（不是写操作，不进 interrupt 流程）。
- 执行结果写入 `AgentState.todos`（新增字段，list[dict]），并记录一条 operation_log。

### 状态透传

- `app/agent/state.py`：`AgentState` 新增 `todos` 字段。
- `app/api/agent.py` 的 `_sync_payload`：透传 `todos`，随 SSE 自动推给前端。
- 因存于 thread state，页面刷新 / SSE 重连后自动恢复。

## Skill 指引（`skills/radiomics-workflow/SKILL.md`）

新增约定：

1. 收到"开始分析"类请求时，先调用 `update_todo_list` 建立 7 个宏观步骤（对应 skill 阶段 0–6）。
2. 每进入一个阶段标 `in_progress`，完成标 `completed`，及时更新。
3. **续分析场景（重点）**：勘察后如发现项目已有可用的既有产出，不得从头重做，Todo List 要反映实际起点：
   - 特征已全部提取且参数未变 → 步骤 0–3 直接标 `completed`，从临床核对/分析开始。
   - 特征只提取了一部分 → 特征提取步骤标 `in_progress` 继续提取剩余病例（底层 h5 缓存机制已支持逐病例跳过已完成的，见 `app/feature.py`），前面步骤标 `completed`。
   - 任何复用既有产出的情况，先验证路径与当前队列的相关性（skill 已有此要求）。

## 前端改动

### 新增 `TodoPanel.vue`（`frontend/src/components/`）

- 挂在 `AgentView.vue` 右侧 `.agent-side-panel` 顶部（审批面板之上），可折叠；`todos` 为空时不渲染。
- 每行：状态图标（pending 空心圆 / in_progress 高亮转圈 / completed 绿色勾）+ 步骤文案；顶部显示进度 `已完成 3/7`。
- 样式参考 `AgentChat.vue` 中现有子 Agent 状态卡片。

### 状态接入

- `frontend/src/api/agent.ts`：`AgentState` TS 接口新增 `todos?: TodoItem[]`。
- `frontend/src/stores/agent.ts`：新增 `todos`，`applyState` 中更新。

## 错误与边界

- 模型不调用工具 → 面板不显示，不影响任何现有功能。
- 任务取消 / 失败：保留最后的 todo 状态，不自动清理。
- 面板对所有会话生效，不限于"开始分析"快捷操作。

## 测试

- 后端：`update_todo_list` 工具写 state、`_sync_payload` 透传的单元测试（沿用 `tests/test_agent_tools.py` 模式）。
- 前端：手动验证（开始分析全流程 + 续分析场景）。
