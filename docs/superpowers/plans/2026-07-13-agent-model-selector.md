# Agent 模型选择器实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Agent 聊天界面输入框右侧、发送按钮左侧添加 `deepseek-v4-flash` / `deepseek-v4-pro` 模型选择器，默认 `deepseek-v4-flash`，并同步从项目配置中移除 LLM 模型字段。

**Architecture:** 模型选择状态保存在 `AgentChat.vue` 本地，通过事件同步给 `AgentView.vue`；创建线程时由 `AgentView.vue` 将选中模型传给 `agentStore.ensureThread`，最终通过 API 传给后端。项目配置前后端均删除 `llm_model` 字段，分析运行时仍默认使用 `deepseek-v4-pro`。

**Tech Stack:** Vue 3, Element Plus, Pinia, TypeScript, FastAPI, Pydantic, PyYAML

---

## File Structure

| File | Responsibility |
|------|----------------|
| `app/api/projects.py` | FastAPI `UpdateConfigRequest` schema，删除 `llm_model` |
| `app/projects.py` | 项目配置默认/读取/保存逻辑，删除 `llm_model` |
| `frontend/src/api/projects.ts` | 前端 `AnalysisConfig` / `UpdateConfigRequest` 类型，删除 `llm_model` |
| `frontend/src/api/runs.ts` | `RunRecord` 保留后端返回字段；`startRun` 仍接收 `AnalysisConfig` |
| `frontend/src/components/AnalysisForm.vue` | 项目配置表单，删除 LLM 模型表单项 |
| `frontend/src/stores/agent.ts` | `ensureThread` 改为接收 `apiKey` 和 `llmModel` |
| `frontend/src/components/AgentChat.vue` | 添加模型选择器并暴露选择事件 |
| `frontend/src/views/AgentView.vue` | 监听模型选择事件并传给 `ensureThread` |
| `frontend/src/components/__tests__/*.spec.ts` | 前端组件测试数据同步 |
| `frontend/src/stores/__tests__/*.spec.ts` | 前端 store 测试数据同步 |
| `tests/test_api_projects.py` | 后端项目 API 测试同步 |
| `tests/test_projects.py` | 后端项目存储测试同步 |
| `tests/test_api_agent.py` | 后端 Agent API 测试同步 |
| `tests/test_api_runs.py` | 后端 Run API 测试同步 |

---

### Task 1: Backend - 从 UpdateConfigRequest 删除 llm_model

**Files:**
- Modify: `app/api/projects.py:49-60`

- [ ] **Step 1: 修改 Pydantic schema**

```python
class UpdateConfigRequest(BaseModel):
    """Request body for updating a project's analysis configuration."""

    image_dir: str = ""
    clinical_path: str = ""
    output_dir: str = "./outputs"
    modality: str = "auto"
    covariates: str = ""
    model: str = "logistic"
    analysis_model: str = "logistic"
    api_key: str = ""
```

- [ ] **Step 2: 运行后端类型检查**

Run: `python -m py_compile app/api/projects.py`
Expected: 无输出，退出码 0

- [ ] **Step 3: Commit**

```bash
git add app/api/projects.py
git commit -m "refactor(api): remove llm_model from UpdateConfigRequest"
```

---

### Task 2: Backend - 从 ProjectStore 删除 llm_model

**Files:**
- Modify: `app/projects.py:109-119`, `app/projects.py:176-187`, `app/projects.py:206-222`

- [ ] **Step 1: 修改 create_project 默认配置**

```python
            "analysis": {
                "image_dir": "",
                "clinical_path": "",
                "output_dir": "./outputs",
                "modality": "auto",
                "covariates": "",
                "model": "logistic",
                "analysis_model": "logistic",
                "api_key": "",
            },
```

- [ ] **Step 2: 修改 _default_analysis**

```python
    def _default_analysis(self) -> Dict[str, Any]:
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
```

- [ ] **Step 3: 修改 save_project_config**

删除 `llm_model = analysis_config.get("llm_model", "deepseek-v4-pro")` 行，并在 `analysis` 字典中删除 `"llm_model": llm_model,`。

```python
        analysis_model = analysis_config.get("analysis_model", "logistic")
        project_data = {
            "name": project["name"],
            "description": project.get("description", ""),
            "path": str(project_path),
            "created_at": project["created_at"],
            "updated_at": now,
            "analysis": {
                "image_dir": analysis_config.get("image_dir", ""),
                "clinical_path": analysis_config.get("clinical_path", ""),
                "output_dir": analysis_config.get("output_dir", "./outputs"),
                "modality": analysis_config.get("modality", "auto"),
                "covariates": analysis_config.get("covariates", ""),
                "model": analysis_model,
                "analysis_model": analysis_model,
                # api_key is intentionally never persisted to disk.
                "api_key": "",
            },
        }
```

- [ ] **Step 4: 运行后端类型检查**

Run: `python -m py_compile app/projects.py`
Expected: 无输出，退出码 0

- [ ] **Step 5: Commit**

```bash
git add app/projects.py
git commit -m "refactor(projects): remove llm_model from project config storage"
```

---

### Task 3: 前端 API - 从 AnalysisConfig 删除 llm_model

**Files:**
- Modify: `frontend/src/api/projects.ts:1-31`

- [ ] **Step 1: 修改类型定义**

```typescript
export interface AnalysisConfig {
  image_dir: string
  clinical_path: string
  output_dir: string
  modality: string
  covariates: string
  model: string
  analysis_model: string
  api_key: string
}
```

- [ ] **Step 2: 运行前端类型检查**

Run: `cd frontend && npm run type-check`
Expected: 可能因其他文件引用报错，继续后续任务修复

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/projects.ts
git commit -m "refactor(frontend/api): remove llm_model from AnalysisConfig"
```

---

### Task 4: 前端 AnalysisForm - 删除 LLM 模型表单项

**Files:**
- Modify: `frontend/src/components/AnalysisForm.vue:43-48`, `frontend/src/components/AnalysisForm.vue:100-110`, `frontend/src/components/AnalysisForm.vue:114-126`

- [ ] **Step 1: 删除模板中的 LLM 模型表单项**

删除以下内容：

```vue
        <el-form-item label="LLM 模型">
          <el-select v-model="draft.llm_model" placeholder="请选择 LLM 模型">
            <el-option label="DeepSeek-V4 Pro" value="deepseek-v4-pro" />
            <el-option label="DeepSeek-V4 Flash" value="deepseek-v4-flash" />
          </el-select>
        </el-form-item>
```

- [ ] **Step 2: 修改 defaultConfig**

```typescript
const defaultConfig = (): AnalysisConfig => ({
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'CT',
  covariates: '',
  model: 'logistic',
  analysis_model: 'logistic',
  api_key: '',
})
```

- [ ] **Step 3: 修改 configsEqual**

```typescript
function configsEqual(a: AnalysisConfig, b: AnalysisConfig): boolean {
  return (
    a.image_dir === b.image_dir &&
    a.clinical_path === b.clinical_path &&
    a.output_dir === b.output_dir &&
    a.modality === b.modality &&
    a.covariates === b.covariates &&
    a.model === b.model &&
    a.analysis_model === b.analysis_model &&
    a.api_key === b.api_key
  )
}
```

- [ ] **Step 4: 运行前端类型检查**

Run: `cd frontend && npm run type-check`
Expected: 该文件类型检查通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AnalysisForm.vue
git commit -m "refactor(frontend): remove llm_model field from AnalysisForm"
```

---

### Task 5: 前端 Agent Store - 修改 ensureThread 签名

**Files:**
- Modify: `frontend/src/stores/agent.ts:1-13`, `frontend/src/stores/agent.ts:46-61`

- [ ] **Step 1: 删除 AnalysisConfig import 并调整 ensureThread**

删除 `import type { AnalysisConfig } from '@/api/projects'`。

```typescript
import type {
  AgentState,
  AgentMessage,
  PendingPlan,
  PendingCommand,
  PendingScript,
} from '@/api/agent'
```

修改 `ensureThread`：

```typescript
  async function ensureThread(
    projectId: string,
    apiKey: string,
    llmModel: string
  ): Promise<string> {
    if (threadId.value) {
      return threadId.value
    }
    const { thread_id } = await api.createThread(projectId, {
      api_key: apiKey,
      llm_model: llmModel,
    })
    threadId.value = thread_id
    await syncThread()
    connect()
    return thread_id
  }
```

- [ ] **Step 2: 运行前端类型检查**

Run: `cd frontend && npm run type-check`
Expected: 该文件通过，AgentView 调用点会在 Task 7 修复

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/agent.ts
git commit -m "refactor(frontend/store): change ensureThread to accept apiKey and llmModel"
```

---

### Task 6: 前端 AgentChat - 添加模型选择器

**Files:**
- Modify: `frontend/src/components/AgentChat.vue:42-61`, `frontend/src/components/AgentChat.vue:66-113`, `frontend/src/components/AgentChat.vue:195-207`

- [ ] **Step 1: 在模板中插入 el-select**

```vue
      <div class="message-input-area">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="请输入消息，Enter 发送，Shift+Enter 换行"
          aria-label="消息输入"
          :disabled="!agentStore.threadId"
          @keydown="handleKeydown"
        />
        <el-select
          v-model="selectedModel"
          class="model-selector"
          placeholder="选择模型"
          :disabled="!agentStore.threadId"
          @change="handleModelChange"
        >
          <el-option label="DeepSeek-V4 Flash" value="deepseek-v4-flash" />
          <el-option label="DeepSeek-V4 Pro" value="deepseek-v4-pro" />
        </el-select>
        <el-button
          type="primary"
          :icon="Promotion"
          :disabled="!canSend"
          @click="handleSend"
        >
          发送
        </el-button>
      </div>
```

- [ ] **Step 2: 在 script 中定义状态和事件**

```typescript
const emit = defineEmits<{
  'update:model': [model: string]
}>()

const selectedModel = ref('deepseek-v4-flash')

function handleModelChange(value: string): void {
  emit('update:model', value)
}
```

- [ ] **Step 3: 添加选择器样式**

```css
.model-selector {
  width: 150px;
}

.model-selector :deep(.el-select__wrapper) {
  margin-bottom: 1px;
}
```

- [ ] **Step 4: 运行前端类型检查**

Run: `cd frontend && npm run type-check`
Expected: 该文件通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentChat.vue
git commit -m "feat(frontend): add model selector to AgentChat"
```

---

### Task 7: 前端 AgentView - 连接模型选择器到线程创建

**Files:**
- Modify: `frontend/src/views/AgentView.vue:75-90`, `frontend/src/views/AgentView.vue:92-99`, `frontend/src/views/AgentView.vue:11-13`

- [ ] **Step 1: 在 AgentChat 上监听 update:model 事件**

```vue
      <div class="agent-chat-wrapper">
        <AgentChat @update:model="selectedModel = $event" />
      </div>
```

- [ ] **Step 2: 添加 selectedModel ref 并修改 initThread**

```typescript
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const selectedModel = ref('deepseek-v4-flash')

async function initThread(projectId: string): Promise<void> {
  if (agentStore.threadId) {
    await agentStore.reconnect()
  } else {
    const config = projectStore.currentConfig
    if (!config) {
      return
    }
    await agentStore.ensureThread(projectId, config.api_key, selectedModel.value)
  }
}
```

- [ ] **Step 3: 运行前端类型检查**

Run: `cd frontend && npm run type-check`
Expected: 全量通过

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/AgentView.vue
git commit -m "feat(frontend): wire model selector to thread creation"
```

---

### Task 8: 更新前端测试

**Files:**
- Modify: `frontend/src/components/__tests__/AnalysisForm.spec.ts:9-29`
- Modify: `frontend/src/components/__tests__/AgentChat.spec.ts:1-100`
- Modify: `frontend/src/components/__tests__/ProjectList.spec.ts:1-40`
- Modify: `frontend/src/stores/__tests__/agent.spec.ts:60-100`
- Modify: `frontend/src/stores/__tests__/project.spec.ts:1-40`
- Modify: `frontend/src/stores/__tests__/run.spec.ts:1-40`

- [ ] **Step 1: 更新 AnalysisForm.spec.ts 的 mockConfig**

```typescript
const mockConfig = (): AnalysisConfig => ({
  image_dir: '/path/to/images',
  clinical_path: '/path/to/clinical.csv',
  output_dir: './outputs',
  modality: 'CT',
  covariates: 'age,gender',
  model: 'logistic',
  analysis_model: 'logistic',
  api_key: 'sk-test',
})
```

- [ ] **Step 2: 更新其余测试中的 mock 数据**

对所有 mock 对象删除 `llm_model` 字段，保持其他字段不变。

- [ ] **Step 3: 更新 agent.spec.ts 的 ensureThread 调用**

```typescript
await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
```

- [ ] **Step 4: 运行前端测试**

Run: `cd frontend && npm run test:unit`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/__tests__ frontend/src/stores/__tests__
git commit -m "test(frontend): update mocks after removing llm_model"
```

---

### Task 9: 更新后端测试

**Files:**
- Modify: `tests/test_api_projects.py`
- Modify: `tests/test_projects.py`
- Modify: `tests/test_api_agent.py`
- Modify: `tests/test_api_runs.py`

- [ ] **Step 1: 更新 test_api_projects.py 中的配置 payload**

删除所有更新配置请求 payload 中的 `llm_model` 字段。

- [ ] **Step 2: 更新 test_projects.py 中断言**

将 `assert analysis["llm_model"] == ...` 删除或替换为不检查该字段。

- [ ] **Step 3: 更新 test_api_agent.py**

确认 `create_thread` 测试仍传入 `llm_model` 字段（Agent 线程创建逻辑不变，只是来源从项目配置改为前端选择器）。

- [ ] **Step 4: 更新 test_api_runs.py**

RunConfig payload 中删除 `llm_model`；断言后端返回的运行记录若包含 `llm_model` 则应为默认值 `deepseek-v4-pro`。

- [ ] **Step 5: 运行后端测试**

Run: `pytest tests/test_api_projects.py tests/test_projects.py tests/test_api_agent.py tests/test_api_runs.py -v`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add tests
git commit -m "test(backend): update tests after removing project config llm_model"
```

---

### Task 10: 全量验证

- [ ] **Step 1: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无类型错误

- [ ] **Step 2: 前端单元测试全量运行**

Run: `cd frontend && npm run test:unit`
Expected: 全部通过

- [ ] **Step 3: 后端测试全量运行**

Run: `pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 4: Commit（如只修复了验证中发现的问题）**

```bash
git add -A
git commit -m "fix: address verification findings"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - Agent 界面模型选择器位置与选项 → Task 6
   - 默认 `deepseek-v4-flash` → Task 6 Step 2
   - 创建线程时传入模型 → Task 5 + Task 7
   - 从项目配置移除 `llm_model` → Task 1, 2, 3, 4
   - 运行时保持默认 `deepseek-v4-pro` → 不修改 `app/api/runner.py`
   - 测试同步 → Task 8, 9

2. **Placeholder scan:** 无 TBD/TODO，所有代码步骤均给出具体代码。

3. **Type consistency:**
   - `ensureThread(projectId, apiKey, llmModel)` 在 Task 5 定义，Task 7 调用一致。
   - `AnalysisConfig` 删除 `llm_model` 后，所有 mock 与组件同步更新。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-13-agent-model-selector.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
