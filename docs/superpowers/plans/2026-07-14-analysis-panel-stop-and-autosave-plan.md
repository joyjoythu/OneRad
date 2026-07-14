# 分析面板停止分析与自动保存实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在分析面板增加「停止分析」按钮和配置自动保存能力，同时保留手动保存入口并明确 API 密钥不落盘。

**Architecture:** 后端用 `app.state.pipeline_task_map` 记录 `run_id → asyncio.Task`，新增 `POST /api/runs/{run_id}/cancel` 触发取消；`run_pipeline` 捕获取消异常并记录 `cancelled` 状态。前端为输入框增加防抖自动保存，运行时按钮切换为「停止分析」，调用 cancel API。

**Tech Stack:** FastAPI, Python 3.11+, Vue 3, Pinia, Element Plus, Vitest, pytest

---

## 文件结构

| 文件 | 责任 |
|------|------|
| `app/api/__init__.py` | 初始化 `pipeline_task_map` |
| `app/api/runner.py` | 启动/取消 pipeline task，处理取消异常 |
| `app/api/runs.py` | 新增 cancel endpoint |
| `app/projects.py` | 统一 `model`/`analysis_model` 保存逻辑 |
| `tests/test_api_runs.py` | 后端取消 API 测试 |
| `tests/test_api_projects.py` | 配置保存一致性测试 |
| `frontend/src/api/runs.ts` | 新增 `cancelRun` API 调用 |
| `frontend/src/stores/run.ts` | 新增 `cancelling` 和 `stopRun` |
| `frontend/src/components/AnalysisForm.vue` | 自动保存、停止按钮、API key 提示 |
| `frontend/src/views/AnalysisView.vue` | 处理 `stop` 事件 |
| `frontend/src/components/__tests__/AnalysisForm.spec.ts` | 前端表单测试 |
| `frontend/src/stores/__tests__/run.spec.ts` | run store 测试 |

---

## Task 1: 后端初始化 run_id → task 映射

**Files:**
- Modify: `app/api/__init__.py:29`
- Modify: `app/api/runner.py:129-156`
- Test: `tests/test_api_runs.py`

- [ ] **Step 1: 在 lifespan 中初始化 `pipeline_task_map`**

修改 `app/api/__init__.py` 中 lifespan 的初始化部分：

```python
app.state.pipeline_tasks = set()
app.state.pipeline_task_map = {}
```

- [ ] **Step 2: 在 `start_pipeline_task` 中注册和清理映射**

修改 `app/api/runner.py`：

```python
def start_pipeline_task(
    app,
    project_id: str,
    run_id: str,
    config: Dict[str, Any],
    bridge: EventBridge,
    store: ProjectStore,
    loop: asyncio.AbstractEventLoop,
) -> asyncio.Task:
    """Launch a tracked background task that runs the pipeline."""

    async def _tracked_run() -> None:
        task = asyncio.current_task()
        app.state.pipeline_tasks.add(task)
        app.state.pipeline_task_map[run_id] = task
        try:
            await run_in_threadpool(
                run_pipeline,
                project_id,
                run_id,
                config,
                bridge,
                store,
                loop,
            )
        finally:
            app.state.pipeline_tasks.discard(task)
            app.state.pipeline_task_map.pop(run_id, None)

    return asyncio.create_task(_tracked_run())
```

- [ ] **Step 3: 运行现有后端测试确认没破坏启动流程**

Run: `pytest tests/test_api_runs.py -v`
Expected: 现有测试通过

- [ ] **Step 4: Commit**

```bash
git add app/api/__init__.py app/api/runner.py
git commit -m "feat(runner): track pipeline tasks by run_id"
```

---

## Task 2: 后端在 run_pipeline 中处理取消异常

**Files:**
- Modify: `app/api/runner.py:62-127`
- Test: `tests/test_api_runs.py`

- [ ] **Step 1: 编写测试验证取消后状态为 cancelled**

在 `tests/test_api_runs.py` 中新增一个辅助函数和测试：

```python
def _slow_config():
    return {
        "image_dir": "",
        "clinical_path": "",
        "output_dir": "./outputs",
        "modality": "auto",
        "covariates": "",
        "model": "logistic",
        "analysis_model": "logistic",
        "api_key": "",
    }


def test_cancel_run_records_cancelled_status(client, temp_db, monkeypatch):
    store, root = temp_db
    project = store.create_project("Cancel", str(root / "cancel"), "")

    def slow_pipeline(project_id, run_id, config, bridge, store_arg, loop):
        import time
        time.sleep(2)
        store_arg.record_run_end(run_id, "completed", "", "")

    monkeypatch.setattr("app.api.runner.run_pipeline", slow_pipeline)

    start = client.post(f"/api/projects/{project['id']}/runs", json=_slow_config())
    assert start.status_code == 202
    run_id = start.json()["run_id"]

    cancel = client.post(f"/api/runs/{run_id}/cancel")
    assert cancel.status_code == 202

    # Wait for the cancelled task to finish updating the DB.
    time.sleep(0.5)
    run = store.get_run(run_id)
    assert run["status"] == "cancelled"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api_runs.py::test_cancel_run_records_cancelled_status -v`
Expected: 404（因为 cancel endpoint 还不存在）

- [ ] **Step 3: 在 `run_pipeline` 中捕获取消异常**

修改 `app/api/runner.py` 中 `run_pipeline` 的异常处理：

```python
    except Exception as exc:
        tb = traceback.format_exc()
        error_event = {"type": "pipeline_error", "message": str(exc), "traceback": tb}
        publish_event(bridge, loop, run_id, error_event)
        store.record_run_end(run_id, "failed", f"{exc}\n{tb}")
    except BaseException as exc:
        # Raised when the asyncio task is cancelled from outside.
        publish_event(
            bridge,
            loop,
            run_id,
            {"type": "pipeline_cancelled", "message": "用户取消运行"},
        )
        store.record_run_end(run_id, "cancelled", "用户取消")
        raise
```

注意：将 `BaseException` 分支放在 `Exception` 分支之后，这样 `CancelledError` 不会走通用异常分支。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_api_runs.py::test_cancel_run_records_cancelled_status -v`
Expected: 测试通过（此时 cancel endpoint 还没写，测试仍会因 404 失败，等 Task 3 完成后再运行）

> 实际执行时，如果 Step 4 因 404 失败，属于预期；Task 3 完成后再回来跑完整测试。

- [ ] **Step 5: Commit**

```bash
git add app/api/runner.py tests/test_api_runs.py
git commit -m "feat(runner): handle cancellation and record cancelled status"
```

---

## Task 3: 后端新增取消运行 API

**Files:**
- Modify: `app/api/runs.py`
- Test: `tests/test_api_runs.py`

- [ ] **Step 1: 编写测试验证 cancel endpoint**

在 `tests/test_api_runs.py` 新增测试：

```python
def test_cancel_missing_run_returns_404(client):
    response = client.post("/api/runs/non-existent-id/cancel")
    assert response.status_code == 404


def test_cancel_completed_run_returns_409(client, temp_db, monkeypatch):
    store, root = temp_db
    project = store.create_project("Done", str(root / "done"), "")

    def fast_pipeline(project_id, run_id, config, bridge, store_arg, loop):
        store_arg.record_run_end(run_id, "completed", "", "")

    monkeypatch.setattr("app.api.runner.run_pipeline", fast_pipeline)

    start = client.post(f"/api/projects/{project['id']}/runs", json=_run_config())
    run_id = start.json()["run_id"]
    time.sleep(0.2)

    response = client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 409
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api_runs.py::test_cancel_missing_run_returns_404 tests/test_api_runs.py::test_cancel_completed_run_returns_409 -v`
Expected: 404

- [ ] **Step 3: 实现 cancel endpoint**

在 `app/api/runs.py` 中新增：

```python
@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: str,
    request: Request,
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Cancel a running pipeline run."""
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行记录不存在")
    if run.get("status") != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="运行不在运行中"
        )

    task = request.app.state.pipeline_task_map.get(run_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="未找到运行任务"
        )

    task.cancel()
    return {"run_id": run_id, "status": "cancelling"}
```

- [ ] **Step 4: 运行所有 runs 测试确认通过**

Run: `pytest tests/test_api_runs.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add app/api/runs.py tests/test_api_runs.py
git commit -m "feat(api): add cancel run endpoint"
```

---

## Task 4: 后端统一 model/analysis_model 保存逻辑

**Files:**
- Modify: `app/projects.py:308-349`
- Test: `tests/test_api_projects.py`

- [ ] **Step 1: 编写测试验证字段一致性**

在 `tests/test_api_projects.py` 中新增：

```python
def test_update_config_unifies_model_and_analysis_model(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.put(
        f"/api/projects/{project['id']}/config",
        json={
            "image_dir": "/data/images",
            "clinical_path": "/data/clinical.csv",
            "output_dir": "./out",
            "modality": "CT",
            "covariates": "age,gender",
            "model": "logistic",
            "analysis_model": "random_forest",
            "api_key": "secret",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["analysis"]["analysis_model"] == "random_forest"
    assert data["analysis"]["model"] == "random_forest"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api_projects.py::test_update_config_unifies_model_and_analysis_model -v`
Expected: 失败（如果当前保存不一致）

- [ ] **Step 3: 修改 `save_project_config` 统一字段**

在 `app/projects.py` 中：

```python
        analysis_model = analysis_config.get("analysis_model") or analysis_config.get("model", "logistic")
        project_data = {
            ...
            "analysis": {
                ...
                "model": analysis_model,
                "analysis_model": analysis_model,
                ...
            },
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_api_projects.py::test_update_config_unifies_model_and_analysis_model tests/test_api_projects.py::test_update_config_does_not_persist_api_key -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add app/projects.py tests/test_api_projects.py
git commit -m "fix(projects): unify model and analysis_model on save"
```

---

## Task 5: 前端 API 层新增 cancelRun

**Files:**
- Modify: `frontend/src/api/runs.ts`

- [ ] **Step 1: 添加 cancelRun 函数**

在 `frontend/src/api/runs.ts` 中新增：

```typescript
export const cancelRun = async (runId: string): Promise<void> => {
  await client.post(`/runs/${encodeURIComponent(runId)}/cancel`)
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/runs.ts
git commit -m "feat(api): add cancelRun client"
```

---

## Task 6: 前端 run store 新增 stopRun

**Files:**
- Modify: `frontend/src/stores/run.ts`
- Test: `frontend/src/stores/__tests__/run.spec.ts`

- [ ] **Step 1: 更新 run.spec.ts 测试**

在 `frontend/src/stores/__tests__/run.spec.ts` 中新增测试：

```typescript
  it('stopRun calls cancel API and updates state', async () => {
    vi.mocked(client.post).mockResolvedValue({ data: { run_id: 'run-1', status: 'cancelling' } })
    const store = useRunStore()
    await store.startRun('project-1', mockConfig)
    const es = MockEventSource.instances[0]

    const promise = store.stopRun('run-1')
    expect(store.cancelling).toBe(true)
    await promise

    expect(client.post).toHaveBeenCalledWith('/runs/run-1/cancel')
    expect(store.running).toBe(false)
    expect(store.cancelling).toBe(false)
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/run.spec.ts`
Expected: 失败（`stopRun` 未定义）

- [ ] **Step 3: 在 run store 中实现 stopRun**

修改 `frontend/src/stores/run.ts`：

```typescript
  const cancelling = ref(false)

  async function stopRun(runId: string): Promise<void> {
    cancelling.value = true
    try {
      await api.cancelRun(runId)
    } finally {
      disconnect()
      running.value = false
      cancelling.value = false
      if (currentRun.value) {
        currentRun.value.status = 'cancelled'
      }
    }
  }
```

并在 return 中导出 `cancelling` 和 `stopRun`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/stores/__tests__/run.spec.ts`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/run.ts frontend/src/stores/__tests__/run.spec.ts
git commit -m "feat(store): add stopRun and cancelling state"
```

---

## Task 7: 前端 AnalysisForm 增加自动保存、停止按钮和 API key 提示

**Files:**
- Modify: `frontend/src/components/AnalysisForm.vue`
- Test: `frontend/src/components/__tests__/AnalysisForm.spec.ts`

- [ ] **Step 1: 更新 AnalysisForm 测试**

在 `frontend/src/components/__tests__/AnalysisForm.spec.ts` 中新增/替换测试：

```typescript
  it('emits save event when a field is edited (auto-save)', async () => {
    const { store } = await selectProject()
    const wrapper = setupWrapper(store.currentConfig)
    await flushPromises()

    const input = wrapper.find('input[placeholder="请输入影像目录路径"]')
    await input.setValue('/new/images')
    await flushPromises()

    const events = wrapper.emitted('save')
    expect(events).toBeDefined()
    expect(events!.length).toBeGreaterThan(0)
  })

  it('emits stop event when clicking stop button during run', async () => {
    const { store } = await selectProject()
    const runStore = useRunStore()
    runStore.running = true
    const wrapper = setupWrapper(store.currentConfig)
    await flushPromises()

    const stopButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('停止分析'))
    expect(stopButton).toBeDefined()
    await stopButton!.trigger('click')

    expect(wrapper.emitted('stop')).toHaveLength(1)
  })

  it('shows api key hint', async () => {
    const { store } = await selectProject()
    const wrapper = setupWrapper(store.currentConfig)
    await flushPromises()

    expect(wrapper.text()).toContain('API 密钥仅在当前会话中保留')
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/components/__tests__/AnalysisForm.spec.ts`
Expected: 失败（自动保存、停止按钮、提示文案不存在）

- [ ] **Step 3: 修改 AnalysisForm.vue**

修改 `<script setup>` 部分：

```typescript
import { reactive, watch, computed, ref } from 'vue'
import { Document, VideoPlay, VideoPause } from '@element-plus/icons-vue'

const emit = defineEmits<{
  'update:config': [AnalysisConfig]
  save: []
  run: []
  stop: []
}>()

const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const lastSavedAt = ref<string | null>(null)

function debounce(fn: () => void, wait: number): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(fn, wait)
  }
}

const debouncedSave = debounce(() => {
  saveStatus.value = 'saving'
  emit('save')
}, 500)

const onFieldChange = () => {
  debouncedSave()
}

// Update save status when parent reports success.
watch(() => projectStore.loading, (loading) => {
  if (!loading && saveStatus.value === 'saving') {
    saveStatus.value = 'saved'
    lastSavedAt.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
})
```

在模板中为每个输入框添加 `@change="onFieldChange"`：

```vue
<el-input v-model="draft.image_dir" placeholder="请输入影像目录路径" @change="onFieldChange" />
```

按钮区域改为：

```vue
<div class="analysis-form-actions">
  <el-button
    :icon="Document"
    :loading="projectStore.loading"
    @click="handleSave"
  >
    保存配置
  </el-button>
  <el-button
    v-if="runStore.running"
    type="danger"
    :icon="VideoPause"
    :loading="runStore.cancelling"
    @click="handleStop"
  >
    停止分析
  </el-button>
  <el-button
    v-else
    type="primary"
    :icon="VideoPlay"
    :loading="runStore.running"
    @click="handleRun"
  >
    开始分析
  </el-button>
</div>

<p v-if="saveStatus === 'saved' && lastSavedAt" class="save-hint">
  配置已自动保存 · {{ lastSavedAt }}
</p>
<p v-else-if="saveStatus === 'error'" class="save-hint error">
  自动保存失败，请重试
</p>
```

添加 API key 提示：

```vue
<el-form-item label="API 密钥">
  <el-input
    v-model="draft.api_key"
    show-password
    placeholder="请输入 API 密钥"
    @change="onFieldChange"
  />
  <p class="api-key-hint">API 密钥仅在当前会话中保留，不会写入项目文件</p>
</el-form-item>
```

添加事件处理函数：

```typescript
function handleStop(): void {
  emit('stop')
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/components/__tests__/AnalysisForm.spec.ts`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AnalysisForm.vue frontend/src/components/__tests__/AnalysisForm.spec.ts
git commit -m "feat(ui): auto-save, stop button and api key hint in AnalysisForm"
```

---

## Task 8: 前端 AnalysisView 处理 stop 事件并绑定自动保存状态

**Files:**
- Modify: `frontend/src/views/AnalysisView.vue`

- [ ] **Step 1: 添加 handleStop 并传递给表单**

修改 `frontend/src/views/AnalysisView.vue`：

```vue
<AnalysisForm
  :config="projectStore.currentConfig"
  @update:config="handleConfigUpdate"
  @save="handleSave"
  @run="handleRun"
  @stop="handleStop"
/>
```

添加函数：

```typescript
async function handleStop(): Promise<void> {
  if (!runStore.currentRun) {
    ElMessage.warning('没有正在运行的分析')
    return
  }

  try {
    await runStore.stopRun(runStore.currentRun.id)
    ElMessage.success('分析已停止')
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
```

- [ ] **Step 2: 运行前端 type-check**

Run: `cd frontend && npm run type-check`
Expected: 无类型错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/AnalysisView.vue
git commit -m "feat(ui): wire stop analysis event in AnalysisView"
```

---

## Task 9: 集成验证

- [ ] **Step 1: 运行前端完整测试**

Run: `cd frontend && npm run test:unit`
Expected: 全部通过

- [ ] **Step 2: 运行后端完整测试**

Run: `pytest tests/test_api_runs.py tests/test_api_projects.py -v`
Expected: 全部通过

- [ ] **Step 3: 手动冒烟测试（可选）**

1. 启动后端：`uvicorn main:app --reload`
2. 启动前端：`cd frontend && npm run dev`
3. 创建一个项目，填写配置，观察自动保存提示。
4. 点击「开始分析」，然后点击「停止分析」，确认状态变为 cancelled。
5. 刷新页面，确认除 API 密钥外其他字段已恢复。

- [ ] **Step 4: Commit（如只做了代码修改）**

```bash
git commit -m "chore: integrate stop analysis and auto-save" --allow-empty
```

---

## 自审清单

### Spec 覆盖

| Spec 要求 | 实现任务 |
|-----------|----------|
| 新增停止分析按钮 | Task 7, Task 8 |
| 取消后标记 cancelled 并保留中间文件 | Task 2, Task 3 |
| 自动保存配置 | Task 7 |
| 保留手动保存按钮 | Task 7 |
| API 密钥不落盘并提示用户 | Task 7 |
| 统一 model/analysis_model | Task 4 |

### Placeholder 扫描

- [x] 无 TBD/TODO
- [x] 每个步骤包含实际代码或命令
- [x] 无 "add appropriate error handling" 等模糊描述
- [x] 类型和方法名在前后任务中一致（`stopRun`, `cancelRun`, `cancelling`）

### 类型一致性

- `stopRun(runId: string)` 与 `cancelRun(runId: string)` 签名一致。
- `cancelling` 在 store、AnalysisForm 模板和测试中使用同一名称。
- 后端 cancel endpoint 返回 `{"run_id", "status": "cancelling"}`，前端不依赖该返回值。
