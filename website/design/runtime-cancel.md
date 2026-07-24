# 运行时上下文与取消机制

## 跨线程通信问题与 AgentRunContext

LangGraph 的图节点（`call_llm`、`execute_confirmed` 等）是普通同步函数，运行在 `run_in_threadpool` 的工作线程中，**无法直接访问** FastAPI 的 `app.state` 或 asyncio 事件循环。而耗时操作需要：

1. **推送实时进度** → 需要访问 EventBridge 和主事件循环
2. **响应 /stop** → 需要一个线程安全的中断信号

`app/agent/runtime.py` 提供 AgentRunContext 注册表解决该问题：

```python
@dataclass
class AgentRunContext:
    cancel_event: threading.Event  # /stop 置位，耗时任务轮询
    loop: Any = None               # 主事件循环引用（run_coroutine_threadsafe）
    bridge: Any = None             # EventBridge 实例

_contexts: Dict[str, AgentRunContext] = {}  # thread_id → ctx（锁保护）
# register() / get() / request_cancel() 三个操作均为线程安全
```

## 进度推送的跨线程路径

工作线程中的 `_publish_agent_progress` 经 `agent_runtime.get(thread_id)` 取回上下文，通过 `asyncio.run_coroutine_threadsafe(ctx.bridge.publish(...), ctx.loop)` 把事件安全地提交到主事件循环发布，随后返回继续提取下一个病例。

**关键保护**：`cancel_event.is_set()` 检查在 publish 之前。因为 `/stop` → `cancel_event.set()` → async task cancel 之间有时间窗口，worker 线程可能仍在推送进度——若此时推送 `running: True` 会在前端重新显示 busy 状态。ctx 不存在或已取消时静默跳过。

## 取消的协作式实现

- **/stop 端点**：先 `request_cancel(thread_id)` 置位 `cancel_event`（必须优先执行：后续检查可能因 409 被拒绝，但取消信号必须送达），再 `task.cancel()` 取消 asyncio 流式任务（触发 finally 清理并推送 `running=false`）
- **工作线程轮询**：`FeatureAgent.run` 在每个病例完成后检查 `cancel_event.is_set()`，命中则返回 `{"success": False, "cancelled": True}`
- **子 Agent 轮询**：每次 `stream_mode="values"` 迭代后检查 `cancel_event`，命中即退出并标记 `status="cancelled"`

::: warning
Docker / Windows 均无法安全地强杀线程。`cancel_event` 是**协作式**的——耗时任务必须在合适的检查点主动轮询。
:::

## /stop 的收尾清理

1. 取消 asyncio 流式任务
2. 清除 checkpoint 中残留的 `interrupt_type` + `pending_*` 字段（防止前端收到 `running=false` 后因 `interrupt_type` 非空而重新弹出审批面板）
3. 修复未应答的 `tool_calls`：为每个缺失 id 写入 `ToolMessage({"cancelled": True, "reason": "用户停止了操作"})`，保证下次 `send_message` 时 LLM 不因 history 格式残缺而 400
4. 补打本轮新消息的时间戳
5. 推送 `running=false` 的最终快照
