# 整体架构

## 系统分层

系统自上而下分为四层：**前端（Vue 3 SPA）、FastAPI 后端、LangGraph 状态图、DeepSeek API**。

- 前端与后端之间通过 **REST API（JSON）** 与 **SSE（EventSource）** 双通道通信
- 后端驱动 LangGraph 状态图执行推理与工具调用，状态快照由 `AsyncSqliteSaver` 持久化
- LLM 调用使用**原生 OpenAI SDK**，以保留 DeepSeek 的 `reasoning_content` 思考链字段

```
┌──────────────────────────────────────────────────────────────┐
│                     前端 (Vue 3 SPA)                          │
│  AgentChat ─── 消息列表 + 输入框 + 模型选择 + 自动审批开关     │
│  ApprovalPanel / PlanEditor / ScriptPanel ── 审批面板          │
│  RadiomicsPanel ── 配对确认 / 提取参数 / 分析参数审批          │
│  SubagentPanel ── 子智能体状态卡片   TodoPanel ── 步骤进度     │
│  Pinia Store: messages, interrupt, pending_*, todos,          │
│               thinking, radiomics_progress, subagentStatuses  │
└──────────────┬──────────────────────────────┬────────────────┘
               │   REST API (JSON)            │   SSE (EventSource)
               ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI 后端                              │
│  /api/agent/threads ── 对话 CRUD + 消息/确认/取消/停止        │
│  /api/sse/events    ── EventBridge (pub/sub + SQLite 持久化)  │
│  内存状态（不落库）: agent_api_keys / auto_approve / streams   │
└──────────────┬───────────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────────┐
│              LangGraph 状态图 (5 节点循环)                     │
│  call_llm → process_tool_calls → human_review/auto_confirm    │
│       ↑          → execute_confirmed ──────────┘              │
│  AsyncSqliteSaver ── checkpoint 持久化                        │
└──────────────┬───────────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────────┐
│  DeepSeek API ── deepseek-v4-flash (默认) / deepseek-v4-pro   │
│  关键特性: reasoning_content (思考链非标字段)                  │
└──────────────────────────────────────────────────────────────┘
```

状态机的详细流转见 [LangGraph 状态机](/design/state-machine)。

## 技术栈

| 层 | 技术 | 版本/说明 |
|----|------|----------|
| Agent 框架 | LangGraph | `StateGraph` + `interrupt()` + `AsyncSqliteSaver` |
| LLM 调用 | 原生 OpenAI SDK | 绕过 LangChain ChatOpenAI（保留 `reasoning_content`） |
| LLM | DeepSeek V4 | `deepseek-v4-flash`（默认）/ `deepseek-v4-pro` |
| 后端 | FastAPI + Starlette | 异步路由 + SSE 流式响应 |
| 数据库 | SQLite | 项目元数据 + 对话元数据 + SSE 事件持久化 |
| 前端 | Vue 3 + Element Plus | Composition API + Pinia + Vue Router + Vite |
| 特征提取 | PyRadiomics | 从 GitHub 源码安装 |
| 建模 | scikit-learn | LASSO + LogisticRegression + StratifiedKFold |
| 报告 | python-docx + Matplotlib | Word 报告 + ROC/校准/DCA 曲线 |

## 部署架构

系统以**单一 Docker 容器**交付，多阶段构建：

- **Stage 1**：`node:20-alpine` 完成前端 `npm build`
- **Stage 2**：基于 `python:3.11-slim` 运行 FastAPI（端口 8000）并托管前端静态文件（`frontend/dist/`）

容器挂载卷与环境变量约定：

| 配置 | 用途 |
|------|------|
| `/app/data` | SQLite 数据库、settings 与 LangGraph checkpoints |
| `/app/output` | 分析结果输出目录 |
| `/data/input` | 宿主机影像数据（bind mount） |
| `ONERAD_DATA_DIR=/app/data` | 数据目录 |
| `ONERAD_ALLOW_REMOTE_FS=1` | 允许容器内浏览挂载数据目录 |
| `ONERAD_FS_ROOTS=/data/input` | 路径选择器展示的数据根目录 |
