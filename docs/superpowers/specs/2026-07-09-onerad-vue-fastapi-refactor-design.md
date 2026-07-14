# OneRad Vue + FastAPI 重构设计

**日期**: 2026-07-09  
**主题**: 将 Gradio 前端替换为 Vue 3 + Vite + TypeScript，后端替换为 FastAPI，保留现有 LangGraph Agent。  
**决策路线**: 最小改动替换方案（方案 A）

---

## 1. 目标

- 完全移除 Gradio 依赖与 `app/ui*.py` 相关代码。
- 新增 Vue 3 单页应用（SPA）作为 OneRad 前端。
- 新增 FastAPI 后端，封装项目、影像组学流水线、AI Agent 能力。
- 生产环境由 FastAPI 托管 Vue 构建产物，保持单服务部署。
- 保留原有 CLI 入口：`python main.py --image-dir ... --clinical ...` 仍可离线运行完整分析。
- 保留 LangGraph Agent 的审批中断能力，并使其状态持久化到数据库。

## 2. 当前状态

- `main.py` 在 `--ui` 或无输入参数时启动 Gradio UI。
- `app/ui.py` 实现项目侧边栏、影像组学分析表单、运行日志、报告下载。
- `app/ui_agent.py` 实现 AI Agent 聊天与三种审批中断面板（文件计划/系统命令/Python 脚本）。
- `app/ui_style.py` 提供 OneRad 品牌 CSS 与 HTML 片段。
- `app/orchestrator.py` 通过同步 generator 驱动影像组学流水线，支持 SSE emitter 回调。
- `app/agent/graph.py` 使用 `MemorySaver` 作为 LangGraph checkpointer，状态仅存内存；需替换为异步持久化方案。
- `app/projects.py` 使用 SQLite 持久化项目与运行记录。

## 3. 约束与关键决策

| 决策项 | 选择 |
| --- | --- |
| Gradio | 完全替换，不保留 fallback |
| 前端托管 | FastAPI 通过 `StaticFiles` 托管 `frontend/dist` |
| 实时通信 | SSE + REST；SSE 支持 `Last-Event-ID` 断线续传 |
| Agent 审批 | 保留可编辑计划表 + 确认/取消中断 |
| 后端双轨 | Orchestrator 负责影像组学流水线，LangGraph 负责 AI Agent |
| UI 组件库 | Element Plus |
| 状态持久化 | LangGraph 改用 `AsyncSqliteSaver`（`langgraph-checkpoint-sqlite` + `aiosqlite`）；SSE 事件缓存到 SQLite |

## 4. 架构

```text
┌─────────────────────────────────────────────────────────────┐
│                        Vue 3 SPA                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Project     │  │  Analysis    │  │  Agent Chat      │  │
│  │  Sidebar     │  │  View        │  │  + Approval      │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         └─────────────────┴─────────────────────┘           │
│                           │                                  │
│                    axios / EventSource                       │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP / SSE
┌───────────────────────────┴─────────────────────────────────┐
│                         FastAPI                              │
│  ┌─────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ /api/projects│  │ /api/runs/*     │  │ /api/agent/*    │ │
│  └──────┬──────┘  └────────┬────────┘  └────────┬────────┘ │
│         │                  │                     │          │
│         ▼                  ▼                     ▼          │
│   ProjectStore      Orchestrator.run()    create_agent_graph()│
│   (SQLite)          (同步 generator)      (LangGraph)        │
│                              │                     │          │
│                              ▼                     ▼          │
│                         SSE queue bridge      AsyncSqliteSaver │
│                         (threadpool +         (aiosqlite 持久化)│
│                          asyncio.Queue)                       │
└─────────────────────────────────────────────────────────────┘
```

### 4.1 目录结构

```text
.
├── app/
│   ├── api/
│   │   ├── __init__.py          # create_app() 工厂函数
│   │   ├── deps.py              # FastAPI 依赖：ProjectStore、checkpointer
│   │   ├── projects.py          # /api/projects/* 路由
│   │   ├── runs.py              # /api/runs/* 路由 + SSE
│   │   └── agent.py             # /api/agent/* 路由 + SSE
│   ├── agent/
│   │   ├── graph.py             # 改用 SqliteSaver
│   │   └── ...                  # 其他节点保持不变
│   ├── orchestrator.py          # 基本不变；若现有事件字段不满足 SSE 消费端，仅补充标准字段，不改变 handler 调用方式
│   ├── projects.py              # 扩展：新增通用 sse_events 表缓存 SSE 事件，并支持幂等运行检查
│   ├── direct_analysis.py       # 不变
│   └── ...                      # 现有业务模块
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── router/
│   │   │   └── index.ts
│   │   ├── stores/
│   │   │   ├── project.ts
│   │   │   ├── run.ts
│   │   │   └── agent.ts
│   │   ├── api/
│   │   │   ├── projects.ts
│   │   │   ├── runs.ts
│   │   │   └── agent.ts
│   │   ├── components/
│   │   │   ├── ProjectList.vue
│   │   │   ├── AnalysisForm.vue
│   │   │   ├── LogViewer.vue
│   │   │   ├── ReportDownloader.vue
│   │   │   ├── AgentChat.vue
│   │   │   ├── PlanPanel.vue
│   │   │   ├── CommandPanel.vue
│   │   │   └── ScriptPanel.vue
│   │   └── views/
│   │       ├── AnalysisView.vue
│   │       └── AgentView.vue
│   └── dist/                    # 构建产物（gitignore）
├── main.py                      # 启动 FastAPI / CLI
├── requirements.txt             # 移除 gradio，新增 fastapi/uvicorn
└── docs/superpowers/specs/...
```

## 5. API 设计

### 5.1 项目

- `GET /api/projects` — 项目列表
- `POST /api/projects` — 创建项目 `{name, path, description}`
- `GET /api/projects/{project_id}` — 项目详情 + 当前配置
- `PUT /api/projects/{project_id}/config` — 保存分析配置
- `DELETE /api/projects/{project_id}` — 删除项目
- `GET /api/projects/{project_id}/runs` — 历史运行记录

### 5.2 运行与流水线

- `POST /api/projects/{project_id}/runs` — 触发一次运行
  - 返回 `{run_id}`
  - 后端检查该项目是否已有 `running` 状态 run，若有则返回 409
- `GET /api/runs/{run_id}` — 运行状态与报告路径
- `GET /api/runs/{run_id}/events` — SSE 事件流
  - 支持请求头/查询参数 `Last-Event-ID`
  - 事件格式：
    ```json
    id: 1
    event: pipeline
    data: {"type":"stage_start","stage":"DISCOVERY","message":"开始: DISCOVERY","payload":{}}
    ```

### 5.3 Agent

- `POST /api/agent/threads?project_id={id}` — 创建线程
- `GET /api/agent/threads/{thread_id}` — 获取线程当前状态（用于页面刷新后恢复）
- `POST /api/agent/threads/{thread_id}/messages` — 发送用户消息 `{content}`
- `GET /api/agent/threads/{thread_id}/events` — SSE 事件流（聊天/中断/日志）
- `PUT /api/agent/threads/{thread_id}/plan` — 更新 pending plan `{plan: [...]}`
- `POST /api/agent/threads/{thread_id}/confirm` — 确认中断并恢复
- `POST /api/agent/threads/{thread_id}/cancel` — 取消中断并恢复

### 5.4 静态资源

- `GET /` — 返回 `frontend/dist/index.html`
- `/assets/*` — 静态 js/css/字体
- `/api/*` — API 路由
- 其他所有非 API 路径（如 `/agent`）也返回 `frontend/dist/index.html`，由 Vue Router 处理前端路由。

### 5.5 开发模式

- 开发时前端通过 `vite.config.ts` 配置代理，将 `/api` 转发到本地 FastAPI 服务（如 `http://localhost:8000`），避免跨域问题。
- 生产构建后，`frontend/dist` 由 FastAPI `StaticFiles` 托管，无需 CORS。

## 6. 前端结构

### 6.1 路由

- `/` — 影像组学分析页
- `/agent` — AI Agent 页

### 6.2 Pinia Store

- `projectStore`
  - `projects`, `currentProject`, `loading`
  - `loadProjects()`, `selectProject(id)`, `createProject(...)`, `deleteProject(id)`, `saveConfig(config)`
- `runStore`
  - `currentRun`, `logs`, `running`, `reportUrl`
  - `startRun(projectId)`, `connectSSE(runId, lastEventId?)`, `disconnectSSE()`
- `agentStore`
  - `threadId`, `messages`, `interrupt`, `operationLog`
  - `ensureThread(projectId)`, `sendMessage(content)`, `connectSSE()`, `updatePlan(plan)`, `confirm()`, `cancel()`

### 6.3 组件

- `App.vue`：顶部品牌栏 + 左侧 `ProjectList` + 右侧 `<router-view>`
- `ProjectList.vue`：新建/选择/删除项目
- `AnalysisView.vue`：配置表单 + 运行按钮 + `LogViewer` + `ReportDownloader`
- `AgentView.vue`：聊天区 + 中断面板区
- `PlanPanel.vue`：可编辑表格（Element Plus `el-table`）
- `CommandPanel.vue`：只读 Markdown 展示
- `ScriptPanel.vue`：代码高亮预览

## 7. 数据流

### 7.1 影像组学分析

1. 用户选择项目 → `projectStore.selectProject(id)` → `GET /api/projects/{id}` → 表单回填。
2. 用户修改配置 → 点击「保存」→ `PUT /api/projects/{id}/config`。
3. 用户点击「运行分析」→ `runStore.startRun(projectId)`：
   - POST `/api/projects/{id}/runs` 创建 run；
   - 按钮进入 loading/disabled 状态；
   - 打开 `EventSource` 到 `/api/runs/{run_id}/events`；
   - 每收到事件追加到日志区；
   - 完成后展示报告下载链接。
4. 页面刷新 → 前端用 `Last-Event-ID` 重连，后端从 SQLite 缓存中返回未读事件。

### 7.2 AI Agent

1. 用户进入 `/agent` 并选择项目。
2. 首次发送消息 → `agentStore.ensureThread(projectId)` → `POST /api/agent/threads?project_id=...`。
3. 发送消息 → `POST /api/agent/threads/{thread_id}/messages`。
4. 打开 SSE，接收聊天消息与中断事件。
5. 收到 `interrupt_type=file_plan`：
   - 展示 `PlanPanel`，用户可编辑 plan；
   - 点击确认：先 `PUT /api/agent/threads/{id}/plan`，再 `POST /api/agent/threads/{id}/confirm`；
   - 点击取消：`POST /api/agent/threads/{id}/cancel`。
6. 收到 `interrupt_type=system_command` 或 `python_script`：
   - 展示对应只读面板，确认/取消后恢复。
7. 刷新页面 → `GET /api/agent/threads/{thread_id}` 恢复当前状态（消息、pending interrupt、操作日志），SSE 继续推送新事件。

## 8. 可靠性

### 8.1 SSE 断线续传

- 后端维护通用表 `sse_events(scope, scope_id, event_id, data, created_at)`，其中 `scope` 为 `'run'` 或 `'agent_thread'`，`scope_id` 为 run_id 或 thread_id。
- 每条 SSE 事件带自增 `event_id`（按 scope + scope_id 分段自增）。
- 客户端重连时通过请求头 `Last-Event-ID` 或查询参数 `last_event_id` 携带最后收到的事件 ID；后端返回该 ID 之后的事件。若 ID 已过期或不存在，返回最近 N 条（默认 200 条）。
- 定期清理过期事件（如保留 7 天），避免表无限增长。

### 8.2 Agent 中断持久化

- 安装额外依赖：`langgraph-checkpoint-sqlite` 和 `aiosqlite`。
- `app/agent/graph.py` 将 `MemorySaver` 替换为 `AsyncSqliteSaver`：
  ```python
  from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
  checkpointer = AsyncSqliteSaver(db_path)
  graph = builder.compile(checkpointer=checkpointer)
  ```
- FastAPI Agent 端点全部使用 LangGraph 异步 API：`await graph.ainvoke(...)`、`await graph.astream(...)`、`await graph.aupdate_state(...)`、`await graph.aget_state(...)`。
- 中断状态随异步 checkpointer 持久化到 SQLite，后端重启或用户刷新后仍可通过 `await graph.aget_state(config)` 恢复。

### 8.3 运行幂等

- 前端运行按钮在 `runStore.running` 为 true 时 disabled。
- 后端 `POST /api/projects/{project_id}/runs` 先查询 `runs` 表：
  - 若存在 `status='running'` 的 run，返回 `409 Conflict`（前端按钮也会 disabled，双重保险）；
  - 否则创建新 run。
- 若后端进程崩溃导致 `running` 记录残留，提供管理接口或启动时自动将超过 24 小时的 `running` run 标记为 `failed`。

## 9. 错误处理

- 后端：流水线/Agent 异常捕获后，通过 SSE 发送 `type=error` 事件，并更新 run/thread 状态为 failed。
- 前端：axios 响应拦截器统一处理 4xx/5xx，Element Plus `ElMessage` 提示。
- SSE：`EventSource.onerror` 触发指数退避重连；超过最大重试次数后提示用户手动刷新。
- Agent 中断类型必须在 SSE 事件中明确携带 `interrupt_type`，前端不可依赖文本推断。

## 10. 测试

### 10.1 后端

- 使用 `fastapi.testclient.TestClient` 测试项目 CRUD。
- 测试流水线触发与 SSE 事件流（用同步 generator 模拟 Orchestrator）。
- 测试 Agent 创建、消息发送、中断恢复流程。
- 验证 `POST /api/projects/{id}/runs` 幂等性。
- 移除或重写原有针对 Gradio 的 UI 测试（如 `test_ui.py`）。

### 10.2 前端

- Vitest 测试 Pinia store（mock API）。
- 组件快照/行为测试覆盖 `ProjectList`、`AnalysisForm`、`AgentChat`、`PlanPanel`。

### 10.3 端到端（可选）

- Playwright 验证：创建项目 → 填写路径 → 运行 → 看到日志 → 下载报告。

## 11. 迁移步骤概要

1. 新增 `frontend/` 脚手架（Vite + Vue + TS + Element Plus + Vue Router + Pinia + axios）。
2. 实现 `app/api/` 路由与 `create_app()` 工厂。
3. 调整 `app/orchestrator.py` 事件字段：确保每条事件包含 `type`、`stage`、`message`、`payload`，与 SSE 消费端约定一致。
4. 将 LangGraph checkpointer 改为 `AsyncSqliteSaver`（来自 `langgraph-checkpoint-sqlite`），Agent API 端点改用 `graph.ainvoke` / `graph.astream` / `graph.aupdate_state` / `graph.aget_state`。
5. 扩展 `ProjectStore`：新增 `sse_events` 表实现事件缓存、运行幂等检查、可选的 `agent_threads` 记录表。
6. 重写 `main.py`：当命令行未提供 `--image-dir`/`--feature-csv` 等离线分析参数时启动 FastAPI；否则走原有 CLI 离线分析。
7. 删除 `app/ui.py`、`app/ui_agent.py`、`app/ui_style.py`。
8. 更新 `requirements.txt`：移除 `gradio`；新增 `fastapi`、`uvicorn[standard]`、`python-multipart`、`langgraph-checkpoint-sqlite`、`aiosqlite`。
9. 更新 Dockerfile / docker-compose：增加 Node 构建阶段以编译 Vue，最终镜像由 FastAPI 托管构建产物。
10. 更新测试与 README。

## 12. 风险

- **同步流水线阻塞事件循环**：必须通过线程池运行 `Orchestrator.run()`，否则 SSE 会被卡住。
- **SSE 并发与队列泄露**：每个 SSE 连接需独立队列，连接断开时清理。
- **LangGraph AsyncSqliteSaver 写并发上限**：`aiosqlite` 基于 SQLite 单写模型，多用户同时写入仍可能触发 `database is locked`。实现时需设置合理超时（如 `timeout=30`），必要时迁移到 `langgraph-checkpoint-postgres`。
- **路径输入安全**：前端仍让用户填写本地绝对路径，需与现有逻辑保持一致并做好路径校验。
- **Element Plus 体积**：若包体积敏感，可改为按需引入或回退原生 CSS。

---

**状态**: 待用户审阅后进入 implementation plan。
