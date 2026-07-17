# 聊天界面时间戳与 Agent 头像 — 设计文档

日期：2026-07-17
状态：已获用户批准

## 背景与目标

Agent 聊天界面（`frontend/src/components/AgentChat.vue`）目前不显示任何时间信息，消息气泡也没有头像。本次加两个功能：

1. **时间显示**：每条聊天气泡显示消息时间；左侧历史会话列表（`ThreadList.vue`）显示每个会话的最后更新时间。
2. **Agent 头像**：assistant 消息左侧显示机器人图标头像。

### 需求决策（已与用户确认）

- 时间显示范围：消息气泡 + 会话列表，两处都要。
- 消息时间必须**准确持久**：刷新页面、重启服务后，历史消息的时间仍然正确。
- Agent 头像用机器人图标（圆底 + 内联 SVG），不引入图片资源。
- 用户消息**不加**头像，只有 agent 消息有头像。

## 现状

- 后端 `app/api/agent.py` 的 `_render_messages` 把 LangGraph state 里的 LangChain 消息渲染成 `{role, content, tool_calls?}`，无时间戳。会话状态用 `AsyncSqliteSaver` checkpoint 持久化，重启不丢。
- `ThreadSummary` 已带 `created_at` / `updated_at`，前端已拿到数据但未展示。
- 前端 `AgentMessage` 类型（`frontend/src/api/agent.ts`）无 `timestamp` 字段。
- Element Plus 图标库没有机器人图标。

## 设计

### 1. 后端：消息时间戳（写入消息元数据）

时间戳写在每条 LangChain 消息的 `additional_kwargs["timestamp"]` 里（UTC ISO 8601 字符串，`datetime.now(timezone.utc).isoformat()`），随 SQLite checkpoint 一起持久化。时间戳跟着消息本体走，消息增删不会错位。

- **用户消息**：`app/api/agent.py` 的 `_make_message` 创建 `HumanMessage`/`AIMessage`/`SystemMessage` 时直接写入 timestamp。
- **AI / 工具消息**：由图内部节点在运行期间产生，无法在创建点逐个打标。新增 `_ensure_message_timestamps(graph, config)`：
  1. `aget_state` 读当前 state；
  2. 遍历 messages，给没有 timestamp 的消息补打当前 UTC 时间；
  3. 仅当有改动时写回 checkpoint。
- **写回方式（实现中确定）**：优先裸 `aupdate_state`，让 langgraph 依据 checkpoint 的 `versions_seen` 推断写入归属；仅当裸更新抛 `InvalidUpdateError`（仅发生在未经任何节点执行的 input-only checkpoint，不可能有挂起中断）时回退 `as_node="call_llm"`。**禁止**无条件 `as_node`：它会把更新伪装成该节点的写入，使 interrupt 处挂起的任务被跳过，confirm/cancel 恢复静默失效、线程卡死在待确认状态（实现期间实际踩到并有回归测试锁定）。
- **调用点**（保证各路径收敛）：
  - `_stream_agent` 的 `finally` 里 best-effort 调用（`suppress(Exception)` 吞掉异常）——覆盖正常完成、异常、中途取消的运行；补打放在内层 `try`，四行清摆放在内层 `finally`，保证补打期间被再次取消（`CancelledError` 不受 `suppress(Exception)` 拦截）也不会跳过清理；
  - `/stop` 端点补打未应答 tool_call 的 ToolMessage 之后调用一次（同样 `suppress(Exception)` best-effort）。
- **渲染**：`_render_messages` 输出新增 `timestamp` 字段（从 `additional_kwargs` 读取；dict 形式的消息原样透传）。没有 timestamp 的旧消息省略该字段，前端不显示时间——不造假。

### 2. 前端：消息气泡时间

- `frontend/src/api/agent.ts` 的 `AgentMessage` 加 `timestamp?: string`。
- 新增 `frontend/src/utils/time.ts`：`formatMessageTime(iso: string): string`——把 UTC ISO 转成本地时间；当天的消息返回 `HH:MM`，更早的返回 `MM-DD HH:MM`。无效输入返回空串。
- `AgentChat.vue` 每条气泡下方加一行灰色小字时间，`timestamp` 存在才渲染。user / assistant / tool 三种气泡都显示。

### 3. 前端：会话列表时间

- `ThreadList.vue` 每条会话标题下方加一行小字，显示 `updated_at`（为空时回退 `created_at`），用同一个 `formatMessageTime` 格式化。纯展示改动，数据已在 `ThreadSummary` 里。

### 4. 前端：Agent 头像

- 新增 `frontend/src/components/AgentAvatar.vue`：32px 圆形底色 + 内联 SVG 机器人图标，无边框、无交互。
- `AgentChat.vue` 的 assistant 消息行改为 flex 布局：`[AgentAvatar][气泡列]`，头像与气泡顶端对齐。user、tool 消息布局不变，不加头像。

## 错误处理

- `_ensure_message_timestamps` 在流结束 finally 中调用，任何异常吞掉（打日志即可），不影响流的正常收尾。
- 时间戳解析失败 / 字段缺失时，前端不渲染时间行。

## 测试

- 后端 `tests/test_api_agent.py`（追加到现有文件）：
  - `_make_message` 产生的消息带 `additional_kwargs["timestamp"]`；
  - `_render_messages` 输出包含 timestamp；无 timestamp 的消息输出不含该键；
  - `_ensure_message_timestamps` 给缺 timestamp 的 AI/Tool 消息补打并写回 state；已有 timestamp 的消息不被改写。
- 前端：
  - 新文件 `frontend/src/utils/__tests__/time.spec.ts`：`formatMessageTime` 的当天 / 非当天 / 无效输入分支；
  - 现有 `frontend/src/components/__tests__/AgentChat.spec.ts`：渲染 assistant 头像与消息时间；无 timestamp 时不渲染时间；
  - 现有 `frontend/src/components/__tests__/ThreadList.spec.ts`：渲染会话时间。

## 不做的事（YAGNI）

- 不做相对时间（"5 分钟前"）、不做日期分隔线、不做悬停完整时间 tooltip。
- 不给 user / tool 消息加头像。
- 不改图 state schema、不加旁路存储。
