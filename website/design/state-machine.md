# LangGraph 状态机

Agent 的执行核心是一张 **5 节点、2 条件边**的 LangGraph 状态图：`call_llm` 负责 LLM 推理；`process_tool_calls` 解析工具调用并按「免确认/需确认」路由；`human_review` 与 `auto_confirm` 分别对应人工审批与自动审批；`execute_confirmed` 实际执行已确认的操作并把结果注入消息历史，随后回到 `call_llm` 形成循环。

## 图结构定义

```python
# app/agent/graph.py（有精简）
def create_agent_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("call_llm", call_llm)                    # 节点1: LLM 推理
    builder.add_node("process_tool_calls", process_tool_calls) # 节点2: 解析工具调用
    builder.add_node("human_review", human_review)             # 节点3: 人工审批
    builder.add_node("auto_confirm", auto_confirm)             # 节点4: 自动审批
    builder.add_node("execute_confirmed", execute_confirmed)   # 节点5: 执行确认

    builder.add_edge(START, "call_llm")
    builder.add_conditional_edges("call_llm", should_continue,
        {"process_tool_calls": "process_tool_calls", "__end__": END})
    builder.add_conditional_edges("process_tool_calls", route_after_process,
        {"human_review": "human_review", "auto_confirm": "auto_confirm",
         "call_llm": "call_llm"})
    builder.add_edge("human_review", "execute_confirmed")
    builder.add_edge("auto_confirm", "execute_confirmed")
    builder.add_edge("execute_confirmed", "call_llm")

    return builder.compile(checkpointer=checkpointer)
```

## 完整流转路径（superstep）

1. **Superstep 1 · call_llm**：组装 SystemMessage（skills/ 加载）与历史消息，注册工具（按 `allow_subagent`/`readonly` 动态裁剪），流式调用 DeepSeek；每个 delta chunk 的 `reasoning_content` 经 `_publish_thinking` 旁路推送 SSE，最终累积 content + tool_calls 组装 AIMessage。
2. **Superstep 2 · process_tool_calls**：遍历 tool_call 按工具名路由——`update_todo_list` 直接写入 `state.todos`；`dispatch_subagent(explore)` 直接并行执行；需确认工具设置 `pending_*` + `interrupt_type`；免确认工具直接执行返回 ToolMessage。**同一轮至多一个 pending（`confirmation_pending` 标志）**。
3. **Superstep 3a · auto_confirm**（auto_approve=True）：直接输出 `{"confirmed": True}`。
4. **Superstep 3b · human_review**（auto_approve=False）：`interrupt({"type": ..., pending_*: ...})`，图挂起并将中断状态序列化到 checkpoint，等待外部 `Command(resume={"action": "confirm"|"cancel"|"other"})`。
5. **Superstep 4 · execute_confirmed**：按 `interrupt_type` 取对应 `pending_*` 字段——confirmed 时按类型执行（`file_plan → execute_plan()`；`system_command → 沙箱内执行`；`python_script → execute_script_if_safe()`；`radiomics_execution → FeatureAgent.run()`；`radiomics_analysis → run_radiomics_cv_analysis()`；`feature_statistics → run_feature_statistics()`；`subagent_dispatch → _run_subagents()`），并注入 `{"executed": True, "note": ...}`；否则返回 `{"cancelled": True}` + 可选 HumanMessage；最后 `_clear_interrupt()` 清空所有 `pending_*`。
6. **Superstep 5**：回到 call_llm，进入下一轮循环。

## Checkpoint 持久化

使用 `AsyncSqliteSaver`，每次 superstep 结束后自动将 AgentState 完整快照写入 SQLite：

- **持久化内容**：`messages` 列表（含 `additional_kwargs.reasoning_content`）、`todos`、`model`、`project_path`、`base_url`
- **不持久化**：`api_key`（走 `RunnableConfig.configurable`）
- **interrupt 恢复**：`Command(resume=...)` 触发时，LangGraph 从 checkpoint 恢复状态并从中断点继续
- **容错**：`/stop` 后清理残留的 `interrupt_type` 和 `pending_*` 字段，防止前端误弹审批面板；若消息历史末尾有未应答的 `tool_calls`，为每个缺失 id 补一条 `{"cancelled": true}` 的 ToolMessage，避免下次 LLM 调用返回 400

## AgentState 状态设计

AgentState 定义于 `app/agent/state.py`（TypedDict），字段按职责分为五组：

| 分组 | 字段 | 语义 |
|------|------|------|
| 对话核心 | `messages` | `add_messages` reducer 保证消息追加而非覆盖；`AIMessage.additional_kwargs` 携带 `reasoning_content`（思考链全文）与 `timestamp`；ToolMessage 的 `tool_call_id` 与 AIMessage `tool_calls[*].id` 一一对应 |
| 对话核心 | `project_path` / `base_url` / `model` | 当前项目根目录 / LLM API 地址（固定 `https://api.deepseek.com/v1`）/ 当前会话模型名 |
| 安全凭证 | `api_key` (NotRequired) | 仅兼容旧版 checkpoint；新线程通过 `RunnableConfig.configurable.api_key` 传入，避免密钥写入 SQLite |
| 中断状态 | `interrupt_type` | 8 种取值之一：`file_plan` / `system_command` / `python_script` / `radiomics_plan` / `radiomics_execution` / `radiomics_analysis` / `feature_statistics` / `subagent_dispatch`；另有非中断交互 `"choice"`（`ask_user_choice`，不经 human_review） |
| 中断状态 | `pending_*` 系列（9 个） | `pending_plan` / `pending_command` / `pending_script` / `pending_radiomics_plan` / `pending_radiomics_execution` / `pending_radiomics_analysis` / `pending_feature_statistics` / `pending_subagent` / `pending_choice`——**同一时刻至多一个非 None** |
| 用户反馈 | `confirmed` / `choice_answer` / `other_instruction` | True=确认 / False=取消；选择面板提交的答案；用户选择「其他」时输入的替代指令 |
| UI 辅助 | `context_usage` / `todos` | 最近一次 LLM 调用的 token 用量；步骤面板清单（`update_todo_list` 全量替换） |
| UI 辅助 | `tool_outputs` / `operation_log` | 累积型列表字段（reducer 追加）：前端状态栏与日志面板 |

## 关键约束：同一轮只允许一个需确认的工具调用

LLM 可能在单次 `call_llm` 响应中并行发出多个 `tool_calls`。虽然 API 层面已设置 `parallel_tool_calls=False`，工具定义层面仍需防御：`process_tool_calls` 中，当某轮已存在 `confirmation_pending` 时，后续需确认工具直接返回 error ToolMessage（保证每个 `tool_call_id` 都有响应）并跳过。

**设计理由**：如果允许多个 pending 状态，第二个会覆盖第一个的 `pending_*` 字段，导致第一个 `tool_call_id` 永远收不到 ToolMessage；下次 LLM 调用时历史中 assistant 的 `tool_calls` 缺少对应 tool 消息，API 返回 400。

## API Key 的不落库策略

```python
# _resolve_api_key 的三级优先级：
# 1. RunnableConfig.configurable.api_key  （运行时注入，不持久化）
# 2. state.api_key                        （兼容旧 checkpoint）
# 3. 环境变量 OPENAI_API_KEY / DEEPSEEK_API_KEY
```

创建和恢复线程时，前端传回的 API Key 存储在 `app.state.agent_api_keys[thread_id]`（FastAPI 内存字典），在 `_agent_config()` 中注入 `RunnableConfig`；线程删除时同步清理。
