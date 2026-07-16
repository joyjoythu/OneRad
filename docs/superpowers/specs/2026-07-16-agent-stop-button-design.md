# Agent 聊天停止按钮设计

日期：2026-07-16
状态：已批准（用户确认）

## 背景与目标

Agent 聊天在流式运行期间用户无法中止：长时间思考或工具调用只能等待结束。
需要给聊天框加一个停止按钮：

- 当 agent 在运行时（store `busy === true`），发送按钮变为停止按钮。
- 按下后停止当前分析（后端流式任务真正取消），并保留对话上下文，用户可以立刻继续对话。

## 关键约束：历史必须保持合法

停止时如果正好停在"模型已发起工具调用、但工具尚未执行完"的位置，
检查点中消息历史末尾是一个没有 `ToolMessage` 应答的 assistant `tool_calls` 消息。
此时若直接追加新的用户消息，LLM API 会返回 400
（`insufficient tool messages following tool_calls`，即上次修复的问题）。

因此停止后必须修复历史。经用户确认采用的方式：
**为每个未应答的 tool_call 补一条 `ToolMessage`**，内容为
`{"cancelled": true, "reason": "用户停止了操作"}`。
这样对话里能看到停在了哪一步，模型后续也知道该操作被用户中止。

（备选"用 `RemoveMessage` 静默移除未完成调用"已被用户否决。）

## 方案对比

- **A（选定）：取消 asyncio 任务 + 修复历史**
  对齐项目现有的 pipeline 取消模式（`app/api/runs.py` 的 cancel 端点 +
  `app/api/runner.py` 的 `CancelledError` 处理）：登记 thread_id→任务映射，
  停止时 `task.cancel()`，随后修复历史并推送最终状态。改动小、语义干净。
- B：仅前端断开 SSE、清除 busy。后端任务照跑，分析没真停，线程仍被占用
  （再发消息会 409）。排除。
- C：改造 LangGraph 图结构支持中途取消。工作量大，收益不成比例。排除。

## 后端设计

### `app/api/__init__.py`

lifespan 中新增 `app.state.agent_stream_tasks = {}`（thread_id → asyncio.Task）。

### `app/api/agent.py`

1. 任务登记/清理
   - `_start_stream`：`asyncio.create_task(...)` 后登记
     `app.state.agent_stream_tasks[thread_id] = task`。
   - `_stream_agent` 的 `finally`：增加 `app.state.agent_stream_tasks.pop(thread_id, None)`。
   - `asyncio.CancelledError` 继承自 `BaseException`，不被 `_stream_agent`
     现有的 `except Exception` 捕获，会自然传播到 `finally` 完成集合清理；
     无需在 `_stream_agent` 中显式处理取消（最终状态由 stop 端点发布）。

2. 新端点 `POST /threads/{thread_id}/stop`（202）
   - 线程不存在 → 404（复用 `aget_state` 的 KeyError 检查）。
   - `thread_id` 不在 `active_agent_streams`（无活动流），或映射中找不到
     对应任务 → 409 `当前没有正在运行的任务`。
   - 否则：`task.cancel()`；用 `contextlib.suppress(asyncio.CancelledError)`
     `await task` 等待其收尾（`finally` 清理 active 集合与映射）。
   - 历史修复：`aget_state` 取最新状态；若末条消息含未应答 tool_calls，
     为每个缺失 id 构造 `ToolMessage({"cancelled": true, "reason": "用户停止了操作"})`，
     连同 `operation_log` 追加 `"用户停止了当前任务"` 一起 `aupdate_state` 写入。
   - `bridge.publish("agent", thread_id, _sync_payload(最新状态))`，
     前端立即刷新（含"已停止"记录）。随后 SSE 生成器发现线程离开
     active 集合，发出 `agent_end`。
   - 返回 `{"thread_id": ..., "status": "stopped"}`。

3. 辅助函数 `_unanswered_tool_call_ids(messages) -> list[str]`
   返回历史末尾 assistant 消息的 tool_calls 中、尚没有对应 `ToolMessage`
   （按 `tool_call_id` 匹配）的 id 列表。独立纯函数，便于单元测试。

### 已知取舍（不在本次范围）

- `call_llm` 节点内是同步 `invoke`（LangGraph 在线程池中执行），停止不会
  中止已发出的 LLM HTTP 请求——线程池调用会跑完并被丢弃，但流式任务立即
  停止、用户可立刻继续对话。不为此把节点改为异步。
- 待确认中断（`interrupt_type` 非空）时线程不在 active 集合，stop 端点
  返回 409；该场景沿用确认面板的"取消"按钮，停止按钮也不显示。

## 前端设计

### `frontend/src/api/agent.ts`

新增 `stopAgent(threadId): Promise<{ thread_id: string; status: string }>`，
POST `/agent/threads/{thread_id}/stop`。

### `frontend/src/stores/agent.ts`

新增 `stop()` action：

- 无 threadId 时抛错（与 sendMessage 一致）。
- 调用 `api.stopAgent(threadId)`；无论成功失败都在 `finally` 中
  `busy.value = false`（失败时 axios 拦截器已 toast 原因；即便失败，
  后续发送被 409 兜底，状态自愈）。
- 最终消息列表由 stop 端点发布的 SSE 快照刷新（含"已停止"记录），
  `agent_end` 到达后 busy 保持 false（幂等）。

### `frontend/src/components/AgentChat.vue`

- busy 时：发送按钮替换为 `type="danger"` 的"停止"按钮
  （`CircleClose` 图标），点击 emit `stop`。
- 非 busy 时：维持原发送按钮（含原有禁用逻辑）。
- 输入框在 busy 期间仍保持禁用（先停止再输入，与现有交互一致）。

### `frontend/src/views/AgentView.vue`

新增 `handleStop` → `agentStore.stop()`，绑定到 AgentChat 的 `stop` 事件。

## 测试设计

### 后端 `tests/test_api_agent.py`

1. `test_stop_conflict_when_not_running`：真实 graph、空闲线程，
   POST stop → 409。
2. `test_stop_cancels_stream_and_repairs_history`：mock graph——
   `aget_state` 依次返回：①`interrupt_type=None`（发送前检查）、
   ②合法快照（stop 的存在性检查）、③取消后末条为带未应答 tool_calls
   的消息（修复检查）、④修复后状态（发布用）；`astream` 为产出一条
   快照后永久阻塞的假流。
   流程：POST message → 202；等待 thread 进入 active 集合；
   POST stop → 202；断言：
   - `aupdate_state` 被调用一次，其 messages 含 `tool_call_id` 匹配的
     ToolMessage 且内容为 cancelled；
   - 最终 thread 不在 `active_agent_streams`；
   - `agent_stream_tasks` 中无该 thread 的任务。
3. `_unanswered_tool_call_ids` 单测：全部应答 / 部分应答 / 无 tool_calls
   / 空历史 四种输入。

### 前端

- `stores/__tests__/agent.spec.ts`：`stop()` 调用 stop API 并清除 busy；
  API 失败时 busy 同样复位。
- `components/__tests__/AgentChat.spec.ts`：busy 时显示"停止"按钮且点击
  emit `stop`；非 busy 时显示"发送"按钮、无停止按钮。

## 验证

- 后端：`pytest tests/ -q` 全绿。
- 前端：`vitest run`、`type-check`、`lint`、`build` 全绿。
