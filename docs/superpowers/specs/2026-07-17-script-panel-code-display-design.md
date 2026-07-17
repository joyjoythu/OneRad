# Agent 右侧脚本面板显示源码 — 设计

日期：2026-07-17
状态：已批准

## 背景与问题

agent 工作流中 LLM 调用 `execute_python_script` 工具时，后端把代码写入 `agent_scripts/*.py` 并产生 `pending_script` 中断，前端右侧 `ScriptPanel.vue` 负责展示脚本供用户确认。

当前存在数据缺口：后端 `prepare_script()` 返回的 meta 只有 `description / script_path / risk_level / created_at`，**不含源码**；而前端 `PendingScript` 接口声明了 `code` 和 `explanation` 字段。导致右侧面板代码区为空、描述区也为空（字段名不匹配）。

## 目标

用户在 agent 界面右侧能看到待执行 Python 脚本的完整源码和描述（只读），再决定确认/取消。不支持编辑。

## 方案

后端在 `pending_script` 载荷中内联 `code` 字段（脚本为 LLM 生成的分析代码，体积很小，内联无压力），不新增端点、不增加前端请求。

## 改动点

### 后端（1 处）

- `app/code_runner.py` `prepare_script()`：返回的 meta dict 增加 `"code": code`。
  - 下游 `app/agent/nodes.py`（`pending_script = {"tool_call_id": ..., **meta}`）与 `app/api/agent.py` `_sync_payload()` 自动携带该字段，SSE 与 REST 均无需改动。

### 前端（2 处）

- `frontend/src/api/agent.ts`：`PendingScript` 接口 `explanation` → `description`（与后端对齐）；`code: string`、`risk_level: string` 保留。
- `frontend/src/components/ScriptPanel.vue`：描述区改绑 `script.description`；代码块已绑 `script.code`，后端补字段后即可显示。`code` 缺失时显示兜底文案（如"脚本内容不可用"），面板不崩。

## 数据流（改动后）

1. LLM 调用 `execute_python_script(description, code)` → `prepare_script` 写文件并返回含 `code` 的 meta；
2. `nodes.py` 设 `interrupt_type="python_script"` + `pending_script`（含 `code`）；
3. `_sync_payload()` → SSE `agent` 事件 / REST 响应推送 `pending_script`；
4. 前端 store `applyState` 写入 `pendingScript` → `AgentView` 渲染 `ScriptPanel`，显示描述 + 源码；
5. 用户确认/取消流程不变。

## 错误处理

- `code` 为空或缺失：面板显示兜底文案，确认/取消按钮功能不受影响。
- 后端写文件失败、风险拒绝等既有行为不变。

## 测试

- `tests/test_code_runner.py`：断言 meta 含 `code` 且与写入文件内容一致。
- `tests/test_agent_tools.py`：断言工具返回的 script meta 含 `code`。
- 前端 `frontend/src/stores/__tests__/agent.spec.ts`：如断言 `PendingScript` 形状则同步更新。

## 不做的事（YAGNI）

- 面板内编辑代码后执行
- 脚本超长截断 / 按需拉取端点
- 文件路径打开链接
