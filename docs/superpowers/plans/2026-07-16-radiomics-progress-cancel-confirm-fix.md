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

## 验证

- 后端：`pytest tests/` 380 passed, 1 skipped（新增 `test_agent_runtime.py`，FeatureAgent 进度/取消 3 例，节点上下文透传，stop 协作式取消，`_sync_payload` radiomics 字段）。
- 前端：`vue-tsc` 通过；`vitest run` 74 passed（新增 RadiomicsPanel 组件测试 2 例、store 进度/pending 跟踪 3 例）。
- 已知既有问题：`tests/test_api_agent.py::test_stop_cancels_stream_and_repairs_history` 在全量套件下偶发 2 秒轮询超时（时序敏感，与本次改动无关）。
