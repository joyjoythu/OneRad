# Agent 界面模型选择器设计文档

## 目标

在 Agent 聊天界面的输入区域增加一个模型选择器，允许用户在 `deepseek-v4-flash` 和 `deepseek-v4-pro` 之间切换。选择器放置在输入框右侧、发送按钮左侧。模型选择仅对**新创建的 Agent 会话**生效；已创建的会话保持创建时所选模型不变。同时，从项目配置表单中移除 LLM 模型字段，运行时默认使用 `deepseek-v4-pro`。

## 背景

- 前端技术栈：Vue 3 + Element Plus + Pinia + TypeScript。
- Agent 聊天组件：`frontend/src/components/AgentChat.vue`。
- Agent Store：`frontend/src/stores/agent.ts`，`ensureThread` 负责创建线程，当前从 `AnalysisConfig.llm_model` 取模型。
- 后端 Agent API：`app/api/agent.py`，创建线程接口已接受 `llm_model` 字段。
- 项目配置：`frontend/src/components/AnalysisForm.vue` 与 `app/api/projects.py` 当前包含 `llm_model` 字段。

## 方案

采用**组件本地状态**方案：模型选择状态保存在 `AgentChat.vue`，默认 `deepseek-v4-flash`，创建线程时通过 `AgentView.vue` 传给 `agentStore.ensureThread`。

## 详细设计

### 1. 前端组件 `AgentChat.vue`

- 在 `.message-input-area` 中，于 `el-input` 与发送 `el-button` 之间插入 `el-select`。
- `el-select` 宽度约 `150px`，选项：
  - `deepseek-v4-flash`（默认）
  - `deepseek-v4-pro`
- 使用本地 `ref` 维护 `selectedModel`。
- 通过 `defineEmits(['update:model'])` 在选择变化时通知父组件。
- 发送按钮禁用逻辑不变，仍依赖 `canSend`。

### 2. 视图 `AgentView.vue`

- 新增本地 `ref` 保存当前选中的模型，默认 `deepseek-v4-flash`。
- 监听 `AgentChat` 的 `update:model` 事件更新该 ref。
- 调用 `agentStore.ensureThread(projectId, config.api_key, selectedModel)` 创建线程。

### 3. Store `agent.ts`

- 修改 `ensureThread` 签名：
  ```ts
  async function ensureThread(
    projectId: string,
    apiKey: string,
    llmModel: string
  ): Promise<string>
  ```
- 内部调用 `api.createThread(projectId, { api_key: apiKey, llm_model: llmModel })`。

### 4. 移除项目配置中的 LLM 模型字段

#### 前端

- `frontend/src/api/projects.ts`：从 `AnalysisConfig` 和 `UpdateConfigRequest` 中删除 `llm_model`。
- `frontend/src/components/AnalysisForm.vue`：
  - 删除 LLM 模型 `el-form-item`。
  - 从 `defaultConfig()` 中删除 `llm_model`。
  - 从 `configsEqual()` 中删除 `llm_model` 比较。
- `frontend/src/api/runs.ts`：`RunRecord` 保留后端返回的 `llm_model` 字段；`startRun` 仍接收 `AnalysisConfig`（不再含 `llm_model`），后端使用默认值。

#### 后端

- `app/api/projects.py`：从 `UpdateConfigRequest` 中删除 `llm_model`。
- `app/projects.py`：
  - `create_project` 的默认 `analysis` 字典中删除 `llm_model`。
  - `_default_analysis()` 中删除 `llm_model`。
  - `save_project_config()` 中删除 `llm_model` 读取与写入。
- `app/api/runner.py`：保持不变，运行时通过 `config.get("llm_model", "deepseek-v4-pro")` 使用默认 `deepseek-v4-pro`。

### 5. 测试更新

- 前端测试：
  - `frontend/src/components/__tests__/AnalysisForm.spec.ts`
  - `frontend/src/components/__tests__/AgentChat.spec.ts`
  - `frontend/src/components/__tests__/ProjectList.spec.ts`
  - `frontend/src/stores/__tests__/agent.spec.ts`
  - `frontend/src/stores/__tests__/project.spec.ts`
  - `frontend/src/stores/__tests__/run.spec.ts`
- 后端测试：
  - `tests/test_api_projects.py`
  - `tests/test_projects.py`
  - `tests/test_api_agent.py`
  - `tests/test_api_runs.py`

## 数据流

1. 用户进入 `AgentView`，默认模型为 `deepseek-v4-flash`。
2. 用户可在 `AgentChat` 的选择器切换模型。
3. `AgentView` 收到 `update:model` 事件，更新本地模型 ref。
4. 创建线程时，`AgentView` 将当前选中的模型传入 `agentStore.ensureThread`。
5. `ensureThread` 调用后端 `POST /agent/threads`，携带 `llm_model`。
6. 后端将该模型与线程绑定，后续该线程的 Agent 响应均使用此模型。

## 边界情况

- 未选择项目时：选择器与输入框一并隐藏或禁用（保持现有行为）。
- 已创建线程后切换模型：当前选择器仍可切换，但仅影响下一次创建的新线程；当前线程模型不变。
- 项目配置保存后：不再包含 `llm_model`，不影响运行时默认模型。

## 未来扩展

- 若需要同一会话内切换模型，可在后端增加 `PUT /agent/threads/{thread_id}/model` 接口，并更新 `app.state.agent_llm_models`。
- 若需要运行时也能选择模型，可恢复项目配置中的 `llm_model` 字段，或增加运行时独立选择器。
