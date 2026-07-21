# 用户选择面板（ask_user_choice）设计

日期：2026-07-21

## 背景与目标

当 agent 需要让用户在几个选项中做决定时（如确认分析方案、选择参数），目前只能纯文本提问、用户手动打字回答。目标：agent 可发起结构化提问，前端聊天区内联渲染选择卡片——选项纵向排列、单选高亮、底部"其他"支持自由输入，选中后点提交，对话自动继续。

## 方案：专用回答通道，答案作为工具结果

复用现有 interrupt/resume 链路，新增 `user_choice` 中断类型。答案直接作为提问工具的 ToolMessage 结果返回给模型，对话历史干净；卡片从消息历史重建，可定格回顾。

## 后端改动

### 新工具 `ask_user_choice`（`app/agent/tools.py`）

- 入参：`question: str`、`options: List[str]`（2–8 个，模型只给选项，"其他"由前端固定追加）。
- 返回 `{"_pending_tool": "ask_user_choice", "question": ..., "options": [...]}`，走确认/中断流程；readonly 模式不注册。

### 中断链路（`app/agent/state.py` / `nodes.py` / `graph.py`）

- `AgentState` 新增 `pending_choice: Optional[Dict]`（`{tool_call_id, question, options}`）。
- `process_tool_calls`：`ask_user_choice` 归入需确认集合，`interrupt_type = "user_choice"`。
- `human_review`：interrupt 载荷加 `choice`。
- `execute_confirmed`：新增 `user_choice` 分支——不看 `confirmed`，把 `choice_answer` 作为 ToolMessage（`json {"answer": ...}`）返回给对应 tool_call_id，清中断后回 `call_llm`。
- `AgentState` 新增 `choice_answer: Optional[str]`；`human_review` 从 resume 值 `{"action": "answer", "answer": ...}` 填入。
- `_clear_interrupt` 清理 `pending_choice` / `choice_answer`。

### 新端点（`app/api/agent.py`）

- `POST /threads/{thread_id}/answer`，body `{"answer": str}`：校验非空、当前有中断挂起，`Command(resume={"action": "answer", "answer": ...})` 恢复流。
- `_sync_payload` 透传 `pending_choice`。

## 前端改动

### `ChoicePanel.vue`（新组件，内联于消息流）

- props：`question`、`options`；`answered`（已回答时传入答案文本，卡片只读显示"已选择：X"）。
- 未回答：选项纵向列表单选高亮 + 底部"其他"选项（选中展开输入框）+ 提交按钮（未选择时禁用）。

### 消息流接入（`AgentChat.vue`）

- 渲染消息时检测 assistant 消息中的 `ask_user_choice` 工具调用，渲染 `ChoicePanel`：
  - 对应 ToolMessage 已存在 → `answered` 定格模式；
  - 当前 `interrupt === 'user_choice'` 且为该调用的 pending → 交互模式，提交调 `agentStore.answerChoice(text)`。
- interrupt 期间沿用现有 busy/interrupt 输入禁用逻辑。

### 状态与 API（`stores/agent.ts` / `api/agent.ts`）

- `AgentState` 接口加 `pending_choice`；store 加 `pendingChoice` ref 与 `answerChoice()`（POST answer 后 applyState/连接 SSE 沿用现有模式）。

## 边界与约束

- 一次只挂起一个提问（沿用"同一轮至多一个待确认工具"的现有限制）。
- 取消（/cancel、/stop）沿用现有路径：工具收到 cancelled 的 ToolMessage；interrupt 清除后卡片从消息历史重建，由于 ToolMessage 中无 `answer` 字段，卡片显示"已取消"的只读状态。
- 刷新/重连：interrupt 中的提问由 `pending_choice` 恢复交互卡片；历史问答由消息里的工具调用 + ToolMessage 重建。

## 测试

- 后端：`ask_user_choice` 工具注册与返回、process_tool_calls 设置 `user_choice` 中断、answer 端点恢复后 ToolMessage 携带答案、cancel 路径不受影响（沿用 `tests/test_agent_nodes.py` / `tests/test_api_agent.py` 模式）。
- 前端：手动验证提问 → 选择 → 提交 → 对话继续 → 刷新恢复。
