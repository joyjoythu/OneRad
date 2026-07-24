# 流式通信与前端

## 流式协议与 reasoning_content

### 为什么绕过 LangChain 的 ChatOpenAI

LangChain 的 `ChatOpenAI` 在流式模式下内部用 `ChatCompletionChunk` 拼接最终 AIMessage。DeepSeek 在标准 OpenAI 协议之外增加了 `reasoning_content` 字段（思考链），该字段出现在 delta chunk 中但**不在**最终的 ChatCompletion 响应里，LangChain 的拼接逻辑不认识这个字段，直接丢弃。因此 `call_llm` 中直接用**原生 OpenAI SDK** 做流式调用，完整保留思考链。

### 流式组装的关键逻辑

```python
# _stream_chat_completion（有精简）
stream = client.chat.completions.create(
    model=model, messages=..., tools=...,
    temperature=0.2, parallel_tool_calls=False,
    stream=True, stream_options={"include_usage": True})

reasoning_parts, content_parts, tool_slots = [], [], {}

for chunk in stream:
    if chunk.usage: usage_metadata = {...}          # 流末尾的 usage chunk
    delta = chunk.choices[0].delta
    if delta.reasoning_content:                     # 非标准字段：思考链
        reasoning_parts.append(delta.reasoning_content)
        _publish_thinking(thread_id, "".join(reasoning_parts), done=False)
    if delta.content: content_parts.append(delta.content)
    for tc in (delta.tool_calls or []):             # tool_calls 按 index 分槽累积
        slot = tool_slots.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
        ...  # 同一 tool_call 跨多个 chunk 发送，逐字段拼接

return AIMessage(content=..., tool_calls=...,
    additional_kwargs={"reasoning_content": full_reasoning},  # 随 checkpoint 持久化
    usage_metadata=usage_metadata)
```

## SSE 事件体系与 EventBridge

后端通过 SSE（Server-Sent Events）向前端实时推送状态。EventBridge 是带 SQLite 持久化的 pub/sub 总线；LangGraph 工作线程经 AgentRunContext 跨线程提交事件；前端 EventSource 消费事件并驱动 Pinia store 更新。

### 事件类型一览

| 事件来源 | persist | 触发时机 | 数据格式 |
|---------|---------|---------|---------|
| graph values 快照 | 是 | 每个 superstep 结束 | AgentState（messages + interrupt_type + pending_* + todos + context_usage + running） |
| 思考链 | 否 | 流式 chunk 到达 | `{"thinking": {"text": "...", "done": false}, "running": true}` |
| 提取/转换进度 | 是 | 每个病例提完 / 每个序列转完 | `{"radiomics_progress": {"stage": "extracting" 或 "converting", "current": 5, "total": 30, "patient_id": "..."}, "running": true}` |
| 子 Agent 状态 | 开始/结束持久化，中间滚动不持久化 | 子 Agent 状态变化 | `{"subagent": {"id": "...", "task": "...", "status": "running", "entries": [...]}, "running": true}` |
| 流结束 `agent_end` | — | async generator 正常结束 | `{}` |
| 心跳 `: keep-alive` | — | 每秒（无新事件时） | 注释行 |

### persist 策略的设计逻辑

**高频事件（persist=False）**：thinking delta 每个 token chunk 都推送累积全文、子 Agent 中间滚动每个工具轮次都更新，每秒可能推送多次——若全部持久化，SQLite 写入成为瓶颈（每秒数十次 INSERT），且回放无价值（用户只需要看到最新状态）。

兜底机制：页面刷新后调用 `GET /threads/{id}` 获取完整 values 快照，快照中 `AIMessage.additional_kwargs.reasoning_content` 含完整思考链；子 Agent 开始/结束状态 `persist=True`，重连后可判断是否有正在运行的子 Agent。

**低频事件（persist=True）**：graph values 快照（每个 superstep 一次）、提取进度（每个病例一次，典型场景 30–100 个病例）、子 Agent 开始/结束。

### 进度补偿机制

**场景**：用户刷新页面时特征提取正在进行中。刷新后 `GET /threads/{id}` 返回的 values 快照不含 `radiomics_progress`（它不在 state 中），SSE 也只接收订阅后的新事件，刷新前的进度事件不会重放，**前端进度条消失**。

**解决方案**：`thread_events` 端点中，若为新订阅且线程仍在 `active_agent_streams` 中，则从 SQLite 查询最近一条含 `radiomics_progress` 的持久化事件作为 `catch_up_data`，在 event_generator 开头以 `event: agent` 补发——且**不带 id 行**，让浏览器的 Last-Event-ID 保持未设置，自动重连时仍走同样的补偿逻辑而非回放全部历史。

### publish 原子性与 subscribe 间隙消除

EventBridge（`app/api/sse.py`）维护每 scope 的订阅队列字典（maxsize=256）、scope 锁、单调 id 分配器与进行中写任务集合：

- **publish**：scope 锁内单调分配 event_id；persist 时以 `asyncio.shield` 保护写库任务不被发布者取消传播；推送到在线订阅者时若队列满则丢弃最旧事件
- **subscribe**：锁内先等待所有进行中写任务落库，确认数据库最大 event_id，再注册新订阅队列并回放 `last_event_id` 之后的历史事件——回放与注册在同一锁内完成，保证不遗漏间隙事件，之后转入实时推送

## 前端状态管理

### Pinia Store 核心状态

| 分组 | 字段 |
|------|------|
| 对话状态 | `threadId`（当前活跃对话）、`messages`（由后端 values 快照全量替换）、`interrupt`（驱动审批面板显示）、`busy`（完全由 running 字段驱动） |
| 中断数据 | `pendingPlan` / `pendingCommand` / `pendingScript` / `pendingRadiomicsPlan` / `pendingRadiomicsExecution` / `pendingRadiomicsAnalysis` / `pendingFeatureStatistics` / `pendingSubagent` |
| 实时旁路数据 | `currentThinking`（思考链）、`radiomicsProgress`（提取/转换进度条）、`subagentStatuses`（多子 Agent 并行展示）、`todos`（右侧步骤面板） |
| 对话管理 | `threads`（扁平列表）、`threadsByProject`（按项目分组缓存）、`runningThreadIds`（侧边栏转圈）、`finishedThreadIds`（结束未读提示点） |
| 用户偏好 | `autoApprove`、`selectedModel`（localStorage 持久化） |

### 状态同步与审批流程

用户发消息 → `sendMessage()`：乐观追加用户消息到 messages、busy=true、开启 SSE 连接、`POST /threads/{id}/messages`（后端 202 启动 `_start_stream` → `graph.astream()`）。SSE 事件到达后 `applyState(data)`：messages 全量替换、`interrupt_type` 驱动审批面板、`pending_*` 填充面板数据、thinking/radiomics_progress/subagent/todos 更新对应 UI 状态、running 驱动 busy、context_usage 更新 token 指示器。流结束 `agent_end`：busy=false、清空进度与思考链、`syncThread()` 获取最终 state 兜底收敛、`listThreads()` 刷新侧边栏（首轮对话后标题已生成）。

**审批流程（前端视角）**：SSE 推送 `interrupt_type="file_plan"` → 渲染 PlanEditor.vue；用户编辑计划 → `PUT /threads/{id}/plan` 写回 checkpoint 的 `pending_plan`；点击确认 → `POST /confirm` → 后端 `Command(resume={"action": "confirm"})` → `execute_confirmed` 执行 → 清空 interrupt → 下一轮 SSE 推送 `interrupt_type=null`，面板关闭。取消与「其他」同理，分别走 `POST /cancel` 与 `POST /other`（携带替代指令）。

### busy 约束与轮询收敛

前端状态更新的关键约束：`applyState()` 中 `busy` **完全由后端上报的 `running` 字段驱动**，不能由 `interrupt_type` 推断。原因：`execute_confirmed` 清除 `interrupt_type` 前会有一个中间快照仍带旧值——若用 `interrupt_type != null` 判断 busy，确认后会短暂解除 busy 再恢复，导致 **UI 闪烁**。

`runningThreadIds` 是前端内存状态，刷新后丢失，因此采用双重来源：前端主动标记（sendMessage/confirm/cancel 后立即 add）与后端列表响应（`listThreads()` 中每个 thread 带 running 标志，`syncRunningFromList()` 合并）。刚结束的对话若用户正在看则不加 `finishedThreadIds`，否则加提示点。当 `runningThreadIds` 非空时每 3 秒轮询 `pollRunningProjects()` 刷新相关项目列表，集合清空后自动停止。
