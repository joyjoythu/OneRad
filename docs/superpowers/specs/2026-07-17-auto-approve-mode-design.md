# Agent 自动审批模式 设计文档

日期：2026-07-17
状态：已与用户确认

## 背景与目标

当前 Agent 的 HITL 流程要求用户对每一类风险操作手动确认：文件操作计划（`file_plan`）、系统命令（`system_command`）、Python 脚本（`python_script`）、影像组学方案/执行/分析（`radiomics_plan`/`radiomics_execution`/`radiomics_analysis`）。流程为：`process_tool_calls` 命中需确认工具 → 设置 `interrupt_type` + `pending_*` → `route_after_process` 路由到 `human_review` → LangGraph `interrupt()` 挂起 → 前端对应面板确认/取消 → `execute_confirmed` 执行或取消。

目标：在 UI 模型选择器上方加一个"自动审批"开关。开启后**全部**上述操作跳过人工确认，图不中断、一次跑完。开关支持**会话中实时切换**（对之后的决策点生效；已挂起的审批项仍需手动处理）。

## 关键决策（用户已确认）

1. 覆盖范围：全部六类确认操作自动通过，不做分级。
2. 生效时机：会话中可实时切换，需新增线程级配置更新接口。
3. 已挂起项：打开开关时若已有审批面板弹出，该项仍手动确认/取消，开关只对之后的决策点生效。
4. 实现方案：后端 `route_after_process` 处跳过 `human_review`（方案 A），而非前端监听中断自动 confirm。

## 架构与数据流

- 开关状态后端存于 `app.state.agent_auto_approve: dict[thread_id, bool]`，仿照现有 `agent_llm_models` 的模式，默认 `False`。
- 每次运行开始（发消息、确认、取消恢复都走 `_start_stream` → `_agent_config`），把当前值注入 `config.configurable.auto_approve`，与 `api_key`/`llm_model` 同一条读取路径。
- 决策点 `route_after_process(state, config)` 读 config：开关开且有 `interrupt_type` → 路由到新增 `auto_confirm` 节点（仅置 `confirmed=True`）→ `execute_confirmed` 照常执行并清理 pending 状态 → 回到 `call_llm` 继续，全程不中断。
- 运行途中切换：PUT 接口更新字典，下一次 `_start_stream` 生效。旧 checkpoint 无此字段时默认关闭，完全向后兼容。

## 后端改动

### `app/agent/nodes.py`

- `route_after_process`（现 235 行）：签名加 `config: RunnableConfig`，返回类型 `Literal["human_review", "auto_confirm", "call_llm"]`：
  - 有 `interrupt_type` 且 `config["configurable"].get("auto_approve")` → `"auto_confirm"`
  - 有 `interrupt_type` → `"human_review"`
  - 否则 → `"call_llm"`
- 新增 `auto_confirm(state: AgentState) -> dict`，只返回 `{"confirmed": True}`（`pending_*` 由 `process_tool_calls` 已设置，`execute_confirmed` 负责执行与清理）。

### `app/agent/graph.py`

- 注册 `auto_confirm` 节点；`route_after_process` 条件边映射加 `"auto_confirm": "auto_confirm"`；加边 `auto_confirm → execute_confirmed`。

### `app/api/agent.py`

- `CreateThreadRequest` / `LoadThreadRequest` 加字段 `auto_approve: bool = False`。
- 建线程（约 302-308 行）与载线程（约 403-404 行）处写 `request.app.state.agent_auto_approve[thread_id] = payload.auto_approve`；删线程（约 365-366 行）处 pop。
- 在 `agent_llm_models` 字典初始化处旁边初始化 `agent_auto_approve = {}`。
- `_agent_config`（67-90 行）：`configurable` 加 `"auto_approve": getattr(app.state, "agent_auto_approve", {}).get(thread_id, False)`。
- 新增 `PUT /threads/{thread_id}/auto-approve`，body `{"enabled": bool}`：线程不存在返回 404，否则更新字典并返回 `{"auto_approve": enabled}`。
- `auto_approve` 不持久化到 threads 表（与 `llm_model` 不同）：属临时会话偏好，服务重启后默认关闭即可。

## 前端改动

### `frontend/src/api/agent.ts`

- `createThread` / `loadThread` 请求体加 `auto_approve`。
- 新增 `setAutoApprove(threadId: string, enabled: boolean)` → `PUT /threads/{id}/auto-approve`。

### `frontend/src/stores/agent.ts`

- 新增 `autoApprove = ref(false)` 与 `autoApproveSyncing = ref(false)`。
- `setAutoApprove(enabled: boolean)`：乐观更新；有 threadId 时调 API，失败回滚，错误提示由 axios 拦截器统一 toast（与 `sendMessage`/`confirm` 一致）；API 调用期间置 `autoApproveSyncing`，`finally` 复位。
- `createThread` / `loadThread` 请求带上 `auto_approve: autoApprove.value`（与 `llm_model` 一致：页面刷新后恢复默认关闭，不持久化 UI 偏好）。

### `frontend/src/components/AgentChat.vue`

- 在 `.chat-status`（81-90 行）与 `.message-input-area`（92 行）之间新增一行 `.auto-approve-row`，右对齐放 `el-switch` + "自动审批" 标签，直接绑定 store。右对齐使其正好位于模型选择器（103-110 行）正上方，不挤压现有输入栏横排布局。
- 开关在 busy 与中断挂起中仍可点击；仅在同步请求进行中（`autoApproveSyncing`）短暂禁用，防止快速连点的两次 PUT 乱序完成导致前后端状态不一致。

## 错误处理与边界情况

- PUT 接口对不存在的线程返回 404。
- 前端 API 调用失败：回滚开关状态并提示。
- 中断挂起中打开开关：当前挂起项面板保留，需手动确认/取消；之后的决策点自动通过。
- 运行途中打开开关：本次运行接下来的决策点仍按旧值处理（config 在运行开始时注入），下一次运行/恢复生效；这是可接受的已知边界。
- 无 `auto_approve` 的旧会话/旧 checkpoint：默认 `False`，行为不变。
- 已知残余边界（接受）：同步请求进行中切换线程，若该请求失败回滚，新线程后端字典可能短暂保留乐观值；下一次成功切换或建/载线程会以前端值重新覆盖，自愈。

## 测试

后端：
- `tests/test_agent_nodes.py`：`route_after_process` 三个分支（auto_approve 开/关/无中断）。
- `tests/test_agent_graph.py`：auto_approve 开启时 `process_tool_calls → auto_confirm → execute_confirmed → call_llm` 全路径不产生 interrupt。
- `tests/test_api_agent.py`：PUT 接口（成功更新、404）、建/载线程携带 `auto_approve` 字段。

前端：
- `frontend/src/stores/__tests__/agent.spec.ts`：`setAutoApprove` 乐观更新与失败回滚；create/load 请求携带字段。
- `frontend/src/components/__tests__/AgentChat.spec.ts`：开关渲染在模型选择器上方、绑定 store。

## 不做的事（YAGNI）

- 不做按操作类型分级的部分自动审批。
- 不把 `auto_approve` 持久化到项目配置或 threads 表。
- 不做"打开开关自动确认当前挂起项"。
- 不改 `confirm`/`cancel`/`messages` 等现有接口的载荷。
