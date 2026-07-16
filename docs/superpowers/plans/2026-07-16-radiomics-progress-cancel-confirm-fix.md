# 影像组学提取：进度可见、可停止、可确认 修复记录

**日期:** 2026-07-16
**类型:** Bug 修复（两个关联问题）

## 问题 1：提取开始后"卡住"、无进度、停不掉

**现象:** 用户确认提取影像组学特征后，界面长时间停在"正在思考…"，无法知道提取是否开始、跑到第几例；点击停止无效。

**根因:**

- `execute_confirmed`（`app/agent/nodes.py`）把 `FeatureAgent.run()` 当作一个同步阻塞调用整体执行，逐例跑 PyRadiomics。节点运行期间 LangGraph 不产生中间状态，SSE 零事件，前端无任何进度反馈。
- `/stop` 只是 `task.cancel()` 取消 asyncio 任务，但同步节点实际跑在线程池里，Python 无法杀死运行中的线程；代码中也没有任何协作式取消机制，提取线程会一直跑到完。

**修复:**

- `app/agent/runtime.py`（新增）：以 thread_id 为键的运行时上下文注册表，持有 `cancel_event`、事件循环、SSE 桥。
- `app/feature.py`：`FeatureAgent.run` 新增 `progress_callback` / `cancel_event` 参数；每例开始前上报进度并检查取消事件；取消时保存已完成的部分结果，返回 `cancelled: True`。
- `app/agent/nodes.py`：提取节点通过 `run_coroutine_threadsafe` 向 SSE 推送 `radiomics_progress`（start / extracting(n/total) / finalizing / 结束清除），并把取消事件传入 `FeatureAgent`。
- `app/api/agent.py`：流式任务启动时注册上下文、结束注销；`/stop` 先置位取消事件（工作线程在下一例边界退出）再取消 asyncio 任务。
- 前端：`AgentState` 增加 `radiomics_progress`，store 跟踪并在停止/结束时清除；状态栏显示"正在提取影像组学特征 (n/总数)：patient_id…"等真实进度。

**注意:** 取消是协作式的——正在提取的当前例会跑完才停（通常几十秒内），之后的病例不再执行，已完成部分照常保存。若将来要求立即杀死当前例，需改为子进程方案（`Process.terminate()`）。

## 问题 2：radiomics 中断卡死在"等待确认操作…"

**现象:** LLM 调整配对键名后重新调用提取工具，界面停在"等待确认操作…"，但不展示任何审批内容，也无法取消。

**根因:**

- 后端 `_sync_payload` 不返回 `pending_radiomics_plan` / `pending_radiomics_execution`；
- 前端 `AgentView.vue` 只渲染 `file_plan` / `system_command` / `python_script` 三种确认面板，`radiomics_plan` / `radiomics_execution` 没有任何确认/取消 UI。

**修复:**

- `_sync_payload` 返回两个影像组学 pending 字段；前端 store 同步跟踪（含清空/重置）。
- 新增 `frontend/src/components/RadiomicsPanel.vue`：
  - 特征提取：病例数、YAML 配置、输出目录、完整配对列表，按钮「确认提取 / 取消」；
  - 配对计划：图像/掩膜发现数、高/中/低置信配对数、未匹配数、配对列表，按钮「确认 / 取消」。
- `AgentView.vue` 渲染该面板并补充两种中断的状态标签。

## 问题 3：提取完成后 Agent 无回复，线程卡死在「待确认」状态

**现象:** 提取完成后 Agent 没有返回任何信息，用户也无法发送新消息——发送即被 409 拒绝：「当前存在待确认的操作，请先确认或取消后再发送新消息」。

**根因:**

`FeatureAgent.run` 的返回结果中含有 `feature_df`（pandas DataFrame），而 `execute_confirmed` 节点末尾要 `json.dumps(results)` 生成 ToolMessage——DataFrame 不可 JSON 序列化，节点在**提取完成后**抛 `TypeError` 崩溃。崩溃点位于清空中断状态之前、`call_llm` 总结之前，因此 LLM 从未生成回复，`interrupt_type` 永远停在 `radiomics_execution`，后续消息全被 `send_message` 的 409 检查拦截。提取本身成功（文件已写入），挂在收尾环节。

回归测试 `test_execute_confirmed_radiomics_execution_result_is_json_serializable` 复现了 `TypeError: Object of type DataFrame is not JSON serializable`，与生产现象一致。

**修复:**

- `app/agent/nodes.py` 新增 `_json_safe_radiomics_result`：`_run_radiomics_execution` 返回前先转成 JSON 安全摘要——剔除 DataFrame，保留 success/message/输出路径/成功失败数/失败样例/耗时等字段，特征名截断为前 50 个并附 `n_features` 总数。
- 其余确认分支（`execute_plan`、`_run_system_command`、`execute_script_if_safe`）已核查，返回均为 JSON 安全，无同类问题。

**卡死会话恢复:** pending 状态在 checkpoint 中——重启后端、刷新加载线程，确认面板仍会出现；因特征已提取完，点「取消」后告知 Agent 结果文件位置即可继续。

## 验证

- 后端：`pytest tests/` 381 passed, 1 skipped（新增 `test_agent_runtime.py`，FeatureAgent 进度/取消 3 例，节点上下文透传，stop 协作式取消，`_sync_payload` radiomics 字段，提取结果 JSON 序列化回归）。
- 前端：`vue-tsc` 通过；`vitest run` 74 passed（新增 RadiomicsPanel 组件测试 2 例、store 进度/pending 跟踪 3 例）。
- 已知既有问题：`tests/test_api_agent.py::test_stop_cancels_stream_and_repairs_history` 在全量套件下偶发 2 秒轮询超时（时序敏感，与本次改动无关）。
