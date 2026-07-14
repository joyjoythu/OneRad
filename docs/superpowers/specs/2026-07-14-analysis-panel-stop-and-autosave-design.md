# 分析面板：停止分析与自动保存设计

**日期：** 2026-07-14  
**状态：** 已批准，待实现  
**相关文件：**
- `frontend/src/views/AnalysisView.vue`
- `frontend/src/components/AnalysisForm.vue`
- `frontend/src/stores/run.ts`
- `frontend/src/stores/project.ts`
- `frontend/src/api/runs.ts`
- `frontend/src/api/projects.ts`
- `app/api/runs.py`
- `app/api/projects.py`
- `app/api/runner.py`
- `app/projects.py`
- `app/orchestrator.py`

---

## 背景与问题

当前分析面板存在两个明显体验问题：

1. **无法停止分析**：界面只有「保存配置」和「开始分析」两个按钮。一旦流水线开始运行，用户只能等待完成或出错，无法主动中断长时间运行的任务。
2. **配置保存不可靠**：字段依赖用户点击「保存配置」按钮才能持久化；刷新页面或重启服务后经常需要重新填写。其中 API 密钥目前是故意不落盘的，但用户对此没有感知。

## 目标

- 在分析面板提供「停止分析」能力，取消后运行记录标记为 `cancelled` 并保留已生成的中间文件。
- 引入自动保存，减少用户因忘记点击保存而丢失配置的风险，同时保留手动保存按钮作为显式触发。
- 明确告知用户 API 密钥不会写入磁盘，仅在当前浏览器会话中保留。

## 方案概述

采用「方案 A：自动保存 + 运行中停止」，并保留手动保存按钮：

- 输入框失焦或停止输入 500ms 后自动调用后端保存接口。
- 保存成功后在按钮区域显示轻量提示「配置已自动保存 · 时间」。
- 「保存配置」按钮继续保留，用于立即强制保存并弹出明确成功/失败提示。
- 运行期间「开始分析」按钮变为红色「停止分析」；点击后前端断开 SSE，后端取消对应 task，运行记录更新为 `cancelled`。

## 详细设计

### UI 与交互

```
┌─────────────────────────────────────┐
│ 分析配置 - 测试项目        ● 运行中  │
├─────────────────────────────────────┤
│ 影像目录                            │
│ [/data/images               ]       │
│ 临床数据文件                        │
│ [/data/clinical.csv        ]        │
│ 输出目录                            │
│ [./outputs                 ]        │
│ 影像模态       [CT ▼]               │
│ 分析模型       [随机森林 ▼]         │
│ API 密钥                            │
│ [••••••••                  ]        │
│ API 密钥仅在当前会话中保留，不会... │
│                                     │
│ [保存配置]  [停止分析]              │
│ 配置已自动保存 · 17:32              │
└─────────────────────────────────────┘
```

### 自动保存行为

- **触发条件**：
  - 任意输入框 `change` 事件（失焦）。
  - 任意输入框 `input` 事件防抖 500ms。
- **失败处理**：
  - 自动保存失败时，在按钮下方显示「自动保存失败，请重试」并保留手动保存按钮可用。
  - 不阻塞用户继续编辑。
- **状态提示**：
  - 保存进行中可显示小 spinner 或「保存中…」。
  - 成功后显示「配置已自动保存 · HH:MM」。

### 停止分析行为

1. 用户点击「停止分析」。
2. 前端立即调用 `POST /api/runs/{run_id}/cancel`。
3. 前端断开 SSE 连接，将本地 `running` 状态置为 `false`。
4. 后端在 `app.state.pipeline_task_map` 中通过 `run_id` 找到对应 task，调用 `task.cancel()`。
5. `_tracked_run` async task 收到取消信号后，`run_in_threadpool` 会向工作线程注入 `CancelledError`，`run_pipeline` 捕获后：
   - 发布 `pipeline_cancelled` 事件。
   - 调用 `store.record_run_end(run_id, "cancelled", "用户取消")`。
6. 运行记录状态变为 `cancelled`，已生成文件保留在输出目录中。

### 后端 API 变更

#### 新增接口

```
POST /api/runs/{run_id}/cancel
```

- 返回 `202 Accepted` 表示已发起取消。
- 若运行不存在返回 `404`。
- 若运行已结束（非 running）返回 `409 Conflict`。
- 实现：
  - 启动 task 时把 `(run_id, asyncio.Task)` 存入一个应用级映射 `app.state.pipeline_task_map: dict[str, asyncio.Task]`，取代目前仅保存 task 集合的做法。
  - 取消时通过 `run_id` 查找到对应 task，调用 `task.cancel()`。
  - 状态统一由 `run_pipeline` 的取消处理分支调用 `record_run_end` 更新，避免接口和任务竞争写入。

#### 配置保存接口调整

- `UpdateConfigRequest` 保持向后兼容，继续接受 `model` 和 `analysis_model`。
- `save_project_config` 中统一将 `model` 与 `analysis_model` 设为同一值（取 `analysis_model`），避免前端两个字段不一致导致覆盖。
- `api_key` 继续不写入 `project.yaml`，但接口返回中仍保留空字符串。

### 前端改动

#### `AnalysisForm.vue`

- 保留 `save` / `run` / `update:config` 事件。
- 增加 `stop` 事件。
- 为输入框添加 `change` 和防抖 `input` 监听器，触发 `emit('save')` 进行自动保存。
- 运行时：
  - 「开始分析」按钮隐藏或变为禁用。
  - 显示红色「停止分析」按钮，触发 `emit('stop')`。
- 显示保存状态文本（已保存时间、失败提示）。
- 在 API 密钥输入框下方增加提示文案。

#### `AnalysisView.vue`

- 新增 `handleStop()`：
  - 调用 `runStore.stopRun()`。
  - 失败时通过 `ElMessage` 提示。
- `handleSave()` 保持现有逻辑，可被自动保存和手动点击复用。
- `handleRun()` 保持现有逻辑：先保存配置，再启动运行。

#### `useRunStore` (`run.ts`)

- 新增 `cancelling` ref。
- 新增 `stopRun(runId: string)`：
  - 设置 `cancelling = true`。
  - 调用 `api.cancelRun(runId)`。
  - 成功后断开 SSE，`running = false`，`cancelling = false`。
  - 失败后 `cancelling = false` 并抛出错误。

#### `api/runs.ts`

- 新增 `cancelRun(runId: string): Promise<void>`，调用 `POST /runs/{runId}/cancel`。

### 状态流转

```
[idle] -- startRun --> [running] -- stopRun --> [cancelled]
   |                      |
   |                      +-- complete --> [completed]
   |                      |
   |                      +-- error --> [failed]
   +-- saveConfig -------->
```

### 数据模型

runs 表已包含 `status` 字段，新增 `cancelled` 状态值即可，无需修改 schema。

## 错误处理

- **取消时运行已结束**：后端返回 `409`，前端提示「运行已结束，无需停止」。
- **取消时找不到任务**：可能 task 已完成但 SSE 未同步；后端返回 `404`，前端刷新运行状态。
- **自动保存失败**：显示失败提示，保留手动保存入口；用户可继续编辑。
- **刷新页面**：已保存字段从后端恢复；`api_key` 需重新输入。

## 测试策略

### 后端测试

- `test_api_runs.py` 新增：
  - 取消一个运行中的 run 返回 202，随后状态为 `cancelled`。
  - 取消不存在的 run 返回 404。
  - 取消已完成的 run 返回 409。
- `test_api_projects.py` 新增/更新：
  - 保存配置后 `analysis_model` 与 `model` 保持一致。
  - `api_key` 不写入 `project.yaml`（已有测试）。

### 前端测试

- `AnalysisForm.spec.ts`：
  - 输入字段后触发自动保存（emit save）。
  - 运行时显示「停止分析」按钮并 emit stop。
  - API 密钥输入框下方显示提示文案。
- `run.spec.ts`：
  - `stopRun` 调用 cancel API 并更新 `running` 状态。
  - `cancelling` 状态在请求期间为 true。

## 依赖与限制

- 依赖 FastAPI 的 `asyncio.Task` 取消机制与 `run_in_threadpool` 对 `CancelledError` 的传递行为。
- `Orchestrator.run()` 在 threadpool 中执行，取消信号需要正确传播到生成器循环；若某些 handler 阻塞在 C 扩展中（如 pandas/numpy 计算），取消可能会有延迟。
- 已生成的中间文件保留，但部分文件可能处于不完整状态。

## 非目标

- 暂停/恢复运行（非本次需求）。
- 保存 API 密钥到磁盘（保持现有安全策略）。
- 清理已生成的中间文件（用户选择保留）。
- 运行历史详情页重构。

## 后续可扩展

- 在运行历史列表中显示 `cancelled` 状态的样式。
- 增加全局「正在运行的任务」面板，支持跨项目停止。
- 为长时间 stage 增加可取消的检查点。
