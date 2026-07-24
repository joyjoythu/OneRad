# 子 Agent 系统

## 设计动机与核心思想

完整的影像组学分析需要在项目目录中探索大量信息：目录结构、文件清单、YAML 配置、临床表格列名、图像/mask 配对情况。如果串行在主对话中完成，每一步的中间结果都累积在消息历史中，迅速消耗上下文窗口。

子 Agent 系统的核心思想：

1. **并行加速**——多个独立探索任务同时运行
2. **上下文隔离**——中间过程不进主对话，只有结论返回
3. **安全分级**——explore 模式只读，general 模式需确认

## 两种模式对比

| 维度 | `mode="explore"` | `mode="general"` |
|------|-----------------|-----------------|
| 工具集 | 8 个（仅只读探索工具） | 约 23 个（全部除 dispatch_subagent） |
| confirm 流程 | 无——在 process_tool_calls 中直接执行 | 有——走 auto_confirm（子 Agent 内部 auto_approve=True） |
| 可见性 | 中间过程只推前端，不进主对话 | 中间过程只推前端，不进主对话 |
| 典型用法 | 项目开局探索：扫目录/读配置/查临床表 | 需要写操作或计算的子任务 |
| 并行上限 | 4 worker | 4 worker |
| LLM 调用 | 每次工具调用自动批准 | 每次工具调用自动批准（high 脚本危险标记仍保留） |

## 隔离机制与上下文截断

`_run_subagent` 的核心流程：

1. **派生 thread_id**（父线程 id + `":sub:"` + 随机后缀）
2. **注册运行时上下文**并共享父线程 `cancel_event`（取消传播）
3. **构建独立图与独立 MemorySaver**（不共享父 checkpoint）
4. **组装子配置**：`auto_approve=True`、`allow_subagent=False`（禁止再嵌套）、`readonly_tools` 按模式、`recursion_limit=150`（约 37 轮工具调用）
5. **注入专用 System Prompt**（explore 用只读探索 prompt，general 用全功能 prompt）
6. **流式运行**并滚动推送中间过程到前端
7. **提取结论**（最后一条非空 AIMessage.content）与累计 token 用量，截断返回

**进入主对话的内容**：

- 最终结论截断为 **4000 字符**（`_SUBAGENT_RESULT_MAX_CHARS`）
- 累计 token 用量汇总到 `dispatch_subagent` 返回的 usage 字段

**推送到前端的内容**：

- 滚动窗口最近 **8 条消息摘要**（`_SUBAGENT_ENTRY_WINDOW`），每条摘要截断为 300/200 字符
- 中间滚动 `persist=False`（不写 SQLite），开始/结束 `persist=True`

## 并行执行与取消传播

`_run_subagents` 中，单任务内联执行；多任务时以 `min(len(tasks), 4)` 个 worker 的 `ThreadPoolExecutor` 并行执行并阻塞等待全部完成。每个子 Agent 在独立线程中运行，各自持有独立的图实例和 MemorySaver，线程安全由各模块的独立实例保证（无共享状态）。

**取消传播链**：用户点击 /stop → `request_cancel(parent_thread_id)` → `parent_ctx.cancel_event.set()`；子 Agent 在每次 stream 迭代后检查 `cancel_event`，耗时操作（`FeatureAgent.run`）在每个病例完成后检查；检测到取消立即退出，`status="cancelled"`，返回 `{"success": False, "cancelled": True}`。
