# Agent 界面实时显示模型思考链 — 设计文档

日期：2026-07-18
状态：已批准（头脑风暴确认）

## 背景与目标

当前 Agent 聊天界面在模型推理期间只显示静态文案"正在思考…"（`frontend/src/components/AgentChat.vue:251` 的 `statusText`）。本项目使用 DeepSeek 模型（`deepseek-v4-pro` / `deepseek-v4-flash`），其中 `deepseek-v4-flash` 是推理模型，会输出 `reasoning_content` 思考链，但该字段被 LangChain 客户端层丢弃（`langchain_openai` 不提取非标准字段），且 `call_llm` 是非流式 `.invoke()` 调用。

**目标**：让用户在界面上实时看到模型正在输出的思考链，流式逐段展开；推理结束后思考链以可折叠区块保留在对应 assistant 消息气泡内，刷新页面后仍可回看。

**已确认的需求决策**：

- 显示内容：模型真实推理链（`reasoning_content`），仅推理模型有内容
- 实时性：实时流式，而非每轮完成后一次性显示
- 展示样式：assistant 气泡内可折叠"思考过程"区块；流式期间在消息列表末尾显示实时滚动气泡
- 技术路线：openai SDK 直调 + 旁路事件（仿 `_publish_agent_progress` 模式），不新增依赖

## 总体架构

```
DeepSeek API (stream=True)
    │  reasoning_content / content / tool_calls deltas
    ▼
app/agent/nodes.py  call_llm (改造为流式)
    ├── 累积 reasoning ──► _publish_thinking ──► EventBridge (persist=False)
    │                                                  │ SSE partial: {"thinking": {...}}
    │                                                  ▼
    │                                          前端 store.currentThinking
    │                                                  ▼
    │                                          AgentChat 流式思考气泡
    └── 组装 AIMessage(additional_kwargs["reasoning_content"]) ──► 图状态
                          │  values 快照（现有通路）
                          ▼
              _render_messages 透传 reasoning_content
                          ▼
              历史消息气泡内可折叠"思考过程"区块
```

## 详细设计

### 1. 后端：`app/agent/nodes.py` — `call_llm` 流式改造

- 新增 `_stream_llm()`（或内联于 `call_llm`）：用 `openai` SDK（已是项目依赖，`app/llm.py` 有使用先例）以 `stream=True` 调用 DeepSeek，base_url / api_key / model / temperature 沿用 `_build_llm()`（`nodes.py:25-37`）的现有配置来源。
- tools 通过 `langchain_core.utils.function_calling.convert_to_openai_tool` 从现有工具列表转换为 OpenAI schema。
- 流式循环累积三类 delta：
  - `delta.reasoning_content` → 追加到思考链缓冲，并发布 thinking partial 事件；
  - `delta.content` → 追加到正文缓冲；
  - `delta.tool_calls` → 按 `index` 归并，累积 `id` / `function.name` / `function.arguments`（arguments 为字符串拼接）。
- 流结束后组装 LangChain `AIMessage`：
  - `content` = 正文缓冲；
  - `tool_calls` = 解析后的 `[{name, args, id}]`（arguments JSON 解析失败则抛异常，走现有错误处理，不得带错参数执行工具）；
  - `additional_kwargs["reasoning_content"]` = 完整思考链（无则为空，不设置该键）。
- 返回值与图状态契约不变，下游节点（`process_tool_calls` 等）无需改动。

### 2. 后端：thinking 旁路事件

- 新增 `_publish_thinking()`，仿照 `_publish_agent_progress`（`app/agent/nodes.py:301-318`）：节点线程经 `run_coroutine_threadsafe` 通过 agent_runtime 的 `EventBridge` 发布。
- 载荷格式（partial，`applyState` 按字段合并）：
  - 每轮开始：`{"thinking": {"text": "", "done": false}, "running": true}`（重置）
  - 流式中：`{"thinking": {"text": "<累积全文>", "done": false}, "running": true}`
  - 本轮结束：`{"thinking": {"text": "<累积全文>", "done": true}, "running": true}`
- 发**累积全文**而非增量：丢事件、断线重连均自洽，前端直接整体替换。
- 一轮 agent 运行中多轮 `call_llm`（工具循环）时，每轮重置 text，前端只显示当前轮的流式思考；历史轮次的思考链已由各自 AIMessage 的快照持久化。

### 3. 后端：`EventBridge.publish` 增加 `persist` 开关

- `app/api/sse.py:78-104`：`publish()` 增加 `persist: bool = True` 关键字参数；`persist=False` 时跳过 `record_sse_event` 落库与回放队列，仅做内存 pub/sub。
- thinking partial 事件使用 `persist=False`，避免高频事件撑大 `sse_events` 表（`app/projects.py:474`）。
- 现有调用点行为不变（默认 `True`）。

### 4. 后端：`_render_messages` 透传 reasoning_content

- `app/api/agent.py:149-178`：渲染 `AIMessage` 时，若 `additional_kwargs` 含 `reasoning_content` 则透传到消息 dict，使刷新 / 重连后的历史消息仍携带思考链。

### 5. 前端：类型与 store

- `frontend/src/api/agent.ts`：
  - `AgentMessage` 增加 `reasoning_content?: string`；
  - partial 载荷类型增加 `thinking?: { text: string; done: boolean }`。
- `frontend/src/stores/agent.ts`：
  - 新增 `currentThinking` ref（`{ text: string; done: boolean } | null`）；
  - `applyState()`（58-106）按 `!== undefined` 合并 `thinking` 字段（与 `radiomics_progress` 同模式）；
  - 清空时机：`done=true` 后、values 快照出现新 assistant 消息时、以及 `onEnd` 中（281-298，与 `radiomicsProgress` 同模式），防止残留；
  - **不写入 messages**——快照整体替换 messages 会冲掉本地拼接，流式文本必须走独立 ref。

### 6. 前端：`AgentChat.vue` 渲染

- **流式中**：消息列表末尾（`v-for` 之后）渲染"思考中"气泡：loading 图标 + `currentThinking.text` 实时滚动（自动滚到底部，与现有消息滚动行为一致）。
- **完成后**：assistant 气泡内（18-87 消息循环中）若消息含 `reasoning_content`，渲染可折叠"思考过程"区块，默认折叠；样式与现有气泡协调（Element Plus 组件或原生 details/summary，按现有组件风格选择）。
- **非推理模型**（`deepseek-v4-pro`）：无 `reasoning_content`，不渲染思考区块；现有 `statusText` "正在思考…" 静态文案保留作为兜底。
- 现有 `statusText`、工具调用 `el-tag`、tool 输出折叠等渲染逻辑不变。

### 7. 错误与边界

- 流式调用网络失败 / API 报错 → 抛异常，走图与 `_stream_agent` 的现有错误处理（错误载荷经 SSE 下发，前端 `error` 显示）。
- tool_calls arguments JSON 拼接后解析失败 → 抛异常（安全优先）。
- 用户中途 stop → `/stop` 收尾发最终快照（`agent.py:756-759`），前端 `onEnd` 清空 `currentThinking`。
- 断线重连：thinking partial 不回放；重连后由 values 快照中的完整 `reasoning_content` 兜底，流式气泡消失转为消息内折叠区块。

## 测试计划

- `tests/test_agent_nodes.py`：mock openai SDK 流式响应，验证
  - reasoning 累积与 `additional_kwargs["reasoning_content"]` 写入；
  - 多 chunk tool_calls 的正确归并与 JSON 解析；
  - thinking partial 事件的发布时序（重置 → 累积 → done）。
- `tests/test_api_agent.py`：SSE 流中出现 thinking partial 载荷；`_render_messages` 透传 `reasoning_content`。
- `tests/test_sse.py`（或并入现有 sse 测试）：`publish(persist=False)` 不落库、不出现在回放中。
- `frontend/src/stores/__tests__/agent.spec.ts`：`applyState` 合并 thinking；各清空时机。
- `frontend/src/components/__tests__/AgentChat.spec.ts`：流式思考气泡渲染；历史消息折叠区块渲染；无 `reasoning_content` 时不渲染。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| openai SDK 流式 delta 结构与文档不符（如 reasoning_content 字段名差异） | 实现时先用真实 API 小脚本验证 delta 结构，再写节点代码 |
| 多轮工具循环中 thinking 事件与 values 快照交错导致 UI 闪烁 | 流式气泡只在 `currentThinking` 非空且无新 assistant 消息时显示；快照到达即清空 |
| DeepSeek 非推理模型无 reasoning_content | UI 条件渲染，行为与现状一致 |
| `call_llm` 改造影响现有工具调用链路 | 保持返回值契约（AIMessage）不变；现有 `tests/test_agent_nodes.py` / `test_agent_graph.py` 必须通过 |
