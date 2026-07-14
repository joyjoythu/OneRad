# 按项目历史对话检索与重新加载功能设计

## 背景

当前 Agent 聊天视图（`/agent`）每次进入项目后，只要页面刷新或切换项目，就会丢失之前的对话上下文。后端虽然通过 `AsyncSqliteSaver` 持久化了 LangGraph 的 checkpoint，但：

1. 没有记录 `project_id -> thread_id` 的映射，无法按项目检索历史会话。
2. 前端 `ensureThread` 在 `threadId` 为空时总是创建新线程。
3. 没有 API/界面用于列出、加载、删除历史会话。

本设计目标是为每个项目提供可检索、可重新加载、可删除的多会话历史功能。

## 目标

- 每个项目可拥有多条历史对话。
- 用户可以在 `/agent` 视图左侧会话列表面板中查看、切换、新建、删除会话。
- 加载历史会话时恢复完整 Agent 状态（消息、未确认计划/命令/脚本、操作日志等）。
- 删除会话需要二次确认。

## 非目标

- 不实现跨项目会话共享。
- 不实现会话的导入/导出为文件。
- 不实现复杂的会话搜索、分组、标签功能。
- `api_key` 仍不入库，与现有策略保持一致。

## 方案概述

采用**“projects.db 维护会话元数据表 + checkpoints.db 维护完整状态”**的混合架构：

- 在 `projects.db` 新增 `threads` 表，保存 `thread_id`、`project_id`、`title`、`llm_model`、`created_at`、`updated_at`。
- 会话完整状态继续由现有的 `AsyncSqliteSaver`（`checkpoints.db`）持久化。
- 后端新增按项目列会话、删除会话、重命名会话的 API。
- 前端新增左侧 `ThreadList` 组件，改造 `AgentView` 布局。

## 数据模型

### `threads` 表

```sql
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT,
    llm_model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
```

字段说明：
- `id`：与 LangGraph `thread_id` 一致。
- `project_id`：所属项目。
- `title`：会话标题，自动取第一条用户消息前 30 字符，若无非空消息则使用创建时间。
- `llm_model`：创建会话时选用的模型，加载旧会话时默认沿用。
- `created_at` / `updated_at`：UTC ISO 格式时间戳。

## 后端变更

### 1. `app/projects.py` 新增方法

- `record_thread(project_id, thread_id, title, llm_model)`：创建时写入。
- `list_threads(project_id)`：按 `updated_at DESC` 列出项目下所有会话。
- `update_thread_title(thread_id, title)`：重命名。
- `update_thread_timestamp(thread_id)`：发送消息后更新 `updated_at`。
- `delete_thread(thread_id)`：删除 `threads` 表记录，并级联清理 `checkpoints.db` 与 `sse_events` 中的相关数据。
- `get_thread_meta(thread_id)`：读取单条会话元数据。

### 2. `app/api/agent.py` 新增/改造端点

新增：
- `GET /api/agent/threads?project_id=xxx`
  - 返回：`{ "threads": [ { "id", "project_id", "title", "llm_model", "created_at", "updated_at" } ] }`
- `DELETE /api/agent/threads/{thread_id}`
  - 删除元数据与状态。
- `PATCH /api/agent/threads/{thread_id}`
  - 请求体：`{ "title": "新标题" }`
  - 仅更新标题。

改造：
- `POST /api/agent/threads`：创建 thread 后调用 `record_thread` 写入元数据；标题初始为空，待第一条用户消息发送后再回填。
- `POST /api/agent/threads/{thread_id}/messages`：
  - 发送消息后更新 `updated_at`。
  - 若当前 `title` 为空且消息 role 为 `user`，用消息内容前 30 字符回填 `title`。

### 3. `_agent_config` 与 api_key/model 处理

现有 `_agent_config` 从 `app.state.agent_api_keys` / `agent_llm_models` 读取。服务端重启后这些内存字典会丢失。改造：

- `llm_model`：优先用内存字典，缺失时从 `threads` 表读取。
- `api_key`：继续由调用方（前端当前配置）传入；加载旧会话后，把当前 `api_key` 写回内存字典，保证后续图调用能拿到。

## 前端变更

### 1. 新增组件 `frontend/src/components/ThreadList.vue`

功能：
- 列出当前项目下的历史会话。
- 高亮当前选中的会话。
- 提供“新建对话”按钮。
- 每个会话项提供重命名和删除入口。
- 删除前弹出 `ElMessageBox.confirm` 二次确认。

布局：可折叠的左侧边栏，宽度约 240px。

### 2. 改造 `frontend/src/views/AgentView.vue`

- 在 `agent-workspace` 中把 `ThreadList` 放在 `AgentChat` 左侧。
- 标题栏保留当前项目名称。
- 当项目切换时：
  1. 拉取会话列表。
  2. 若列表非空，默认加载最近一条会话。
  3. 若列表为空，显示“新建对话”提示。

### 3. 更新 `frontend/src/stores/agent.ts`

新增状态：
- `threads: ThreadSummary[]`
- `currentThread: ThreadSummary | null`

新增方法：
- `listThreads(projectId): Promise<void>`
- `loadThread(threadId): Promise<void>`
- `createThread(projectId, apiKey, llmModel): Promise<string>`
- `deleteThread(threadId): Promise<void>`
- `renameThread(threadId, title): Promise<void>`
- `resetThread()` 扩展：同时清空 `threads` 与 `currentThread`。

`ensureThread` 行为保持：若当前没有 `threadId`，则创建新线程；否则复用。

### 4. 更新 `frontend/src/api/agent.ts`

新增接口与函数：
- `ThreadSummary`
- `listThreads(projectId)`
- `deleteThread(threadId)`
- `renameThread(threadId, title)`

## 关键流程

### 新建会话

1. 用户点击“新建对话”。
2. 调用 `POST /api/agent/threads?project_id=xxx`。
3. 后端创建 checkpoint 并写入 `threads` 表（title 为空）。
4. 前端把新会话加入列表并选中，清空聊天输入区。

### 加载历史会话

1. 用户点击列表中的会话。
2. 前端断开旧 SSE，调用 `GET /api/agent/threads/{thread_id}`。
3. 后端返回完整 state，前端 `applyState` 恢复消息、pending plan、operation log 等。
4. 建立 SSE 连接；`_agent_config` 用 `threads` 表中的 `llm_model` 和当前配置中的 `api_key`。

### 继续对话

1. 用户发送消息。
2. 调用 `POST /api/agent/threads/{thread_id}/messages`。
3. 后端更新 `updated_at`；若 title 为空则回填。
4. 启动 graph stream，SSE 推送增量状态。

### 删除会话

1. 用户点击会话项上的删除图标。
2. 前端弹出 `ElMessageBox.confirm`，提示“删除后无法恢复”。
3. 用户确认后调用 `DELETE /api/agent/threads/{thread_id}`。
4. 后端删除 `threads` 记录、`checkpoints.db` 中对应 thread 的 checkpoints、`sse_events` 中对应记录。
5. 前端从列表移除，若删除的是当前会话则清空聊天区。

### 重命名会话

1. 用户点击重命名图标或标题区域。
2. 前端进入内联编辑或弹出输入框。
3. 确认后调用 `PATCH /api/agent/threads/{thread_id}`。
4. 后端更新 `title`，前端刷新列表。

## 安全考虑

- `api_key` 不存入 `threads` 表或任何磁盘文件，保持现有策略。
- 加载旧会话后，把当前用户提供的 `api_key` 写回内存映射，保证 LangGraph 调用可用。
- 删除操作需要二次确认，避免误删。

## 错误处理

- 列表加载失败：前端提示错误，保持当前状态。
- 加载不存在的 thread：后端返回 404，前端提示并刷新列表。
- 删除失败：前端提示错误，不从前端列表移除。
- SSE 重连失败：保持现有重连/报错逻辑。

## 测试计划

### 后端测试

- `test_list_threads_by_project`：创建多个项目与会话，验证列表按项目隔离、按时间倒序。
- `test_delete_thread_cleans_checkpoints`：删除会话后验证 checkpoint 与 sse_events 被清理。
- `test_thread_title_updated_on_first_message`：发送第一条用户消息后验证 title 被回填。
- `test_rename_thread`：验证 PATCH 更新标题。
- `test_load_thread_after_restart`：模拟服务端重启后，用 `llm_model` 元数据加载旧会话。

### 前端测试

- `ThreadList`：渲染列表、高亮当前、触发选择/删除/重命名事件；删除需验证二次确认。
- `AgentView`：切换项目时拉取列表并默认加载最近会话。
- `agentStore`：`listThreads`、`loadThread`、`deleteThread`、`renameThread` 的状态更新。

## 依赖与边界

- 依赖现有 `AsyncSqliteSaver` 接口实现 checkpoint 清理。
- 依赖 `EventBridge` / `ProjectStore` 的 `delete_sse_events` 方法清理事件。
- 不修改 LangGraph 图结构，只增加元数据层。

## 验收标准

- [ ] 每个项目可以在左侧列表看到多条历史会话。
- [ ] 点击历史会话可恢复完整聊天与未确认状态。
- [ ] 新建对话会创建独立的新会话。
- [ ] 删除会话需要二次确认，且删除后数据不可恢复。
- [ ] 重命名会话后列表即时更新。
- [ ] 后端/前端相关测试通过。
