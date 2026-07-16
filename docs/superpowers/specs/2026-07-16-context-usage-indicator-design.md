# 设计：Agent 对话框右下角上下文用量指示

日期：2026-07-16
状态：已获用户批准

## 背景与目标

用户希望在 Agent 聊天对话框的右下角看到一个上下文用量指示，直观了解当前对话占用了模型上下文窗口的多少。经澄清：

- **指标含义**：当前上下文占比——最近一次 LLM 调用的输入 token 数（即当前对话历史实际占用的上下文），并换算成上下文窗口百分比。
- **上下文窗口**：`deepseek-v4-pro` 与 `deepseek-v4-flash` 均按 1,000,000 tokens 计算。
- **实现方案**：方案 A——后端采集 API 返回的真实 `usage_metadata`，随现有状态推送链路下发前端。否决了前端字符估算（偏差大）和 tiktoken 重算（加依赖且 tokenizer 不匹配）。

## 现有架构

- 后端 LangGraph agent：`app/agent/nodes.py` 的 `call_llm` 节点用 `ChatOpenAI` 调 LLM，返回的 `AIMessage.usage_metadata` 目前被丢弃。
- 状态下发：`_sync_payload`（`app/api/agent.py:131`）把 graph state 序列化为 dict，经 REST 响应和 SSE 推送给前端。
- 前端：`frontend/src/stores/agent.ts` 的 `applyState` 应用快照；`AgentChat.vue` 渲染，输入区为 `.message-input-area`（textarea + 模型选择 + 发送/停止按钮）。

## 设计

### 后端

1. **`app/agent/state.py`**：`AgentState` 新增字段
   ```python
   context_usage: Optional[Dict[str, Any]]  # {"input_tokens": int, "output_tokens": int, "total_tokens": int}
   ```
   无 reducer：节点不返回该 key 时自动保留旧值。

2. **`app/agent/nodes.py` `call_llm`**：从 `response.usage_metadata`（langchain 标准属性）提取 token 数，随节点返回值写入 state：
   ```python
   return {"messages": [response], "context_usage": usage}
   ```
   若 API 未返回 usage（某些代理网关），本次不更新该字段，保留旧值；提取逻辑用 `getattr` 防御，绝不影响主流程。

3. **`app/api/agent.py`**：
   - 新增模型上下文窗口映射：`deepseek-v4-pro` / `deepseek-v4-flash` 均为 1,000,000，未知模型默认 1,000,000。
   - `_sync_payload` 返回值新增两个字段：`context_usage`（取自 state，可能为 `None`）和 `context_window`（按 state 中的 `model` 查映射表）。
   - REST 与 SSE 共用 `_sync_payload`，两条链路自动同时生效。

### 前端

4. **`frontend/src/api/agent.ts`**：`AgentState` 类型新增
   ```ts
   context_usage?: { input_tokens: number; output_tokens: number; total_tokens: number } | null
   context_window?: number
   ```

5. **`frontend/src/stores/agent.ts`**：新增 `contextUsage` / `contextWindow` ref；`applyState` 中按 `!== undefined` 判断更新（与现有字段一致的模式）；`resetInternalState` 中清理。

6. **`frontend/src/components/AgentChat.vue`**：在输入区行内、发送/停止按钮左侧放一个紧凑 badge：
   - 内容：图标 + `12.3k/1M · 1.2%`。
   - `el-tooltip` 悬停显示精确明细：输入 / 输出 / 合计 tokens。
   - 颜色阈值：占比 < 80% 普通灰色；≥ 80% 橙色；≥ 95% 红色。
   - 无数据时（新会话尚未调用 LLM）：显示 `--`。
   - 数字格式化：< 1000 显示原数；≥ 1000 显示 `12.3k`；≥ 1M 显示 `1.23M`。

## 数据流

```
call_llm 节点 → response.usage_metadata → AgentState.context_usage
  → checkpointer 持久化 → _sync_payload（附 context_window）
  → REST / SSE → store.applyState → AgentChat.vue badge
```

## 边界情况

- **旧会话**（功能上线前创建的 checkpoint）：state 无 `context_usage` 字段 → 前端显示 `--`，下次 LLM 调用后正常。
- **API 不返回 usage**：保留上一次值；从未有过值则显示 `--`。
- **会话切换 / 新建**：`resetInternalState` 清空，避免串会话显示旧数据。

## 错误处理

无新增失败路径。usage 提取全部防御式（`getattr` / `.get`），失败等同于"无数据"，不抛错、不阻断 LLM 调用。

## 测试

- **后端**（pytest，仿照 `tests/test_agent_nodes.py` 现有 mock 方式）：
  - `call_llm` 从带 `usage_metadata` 的 mock 响应中正确提取并写入 state；
  - mock 响应无 `usage_metadata` 时不更新该字段；
  - `_sync_payload` 包含 `context_usage` 与 `context_window`（已知模型 1M、未知模型默认 1M）。
- **前端**（vitest + @vue/test-utils，补进 `frontend/src/components/__tests__/AgentChat.spec.ts`）：
  - badge 按 store 数据渲染百分比与格式化数字；
  - 无数据时显示 `--`；
  - ≥80% / ≥95% 阈值变色。

## 非目标（YAGNI）

- 上下文压缩 / 截断 / 自动总结提醒；
- 逐条消息 token 明细视图；
- 累计 token 成本统计。
