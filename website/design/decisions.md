# 关键设计决策

## 关键设计决策与权衡

| 决策 | 选择 | 替代方案 | 理由与权衡 |
|------|------|---------|-----------|
| Agent 框架 | **LangGraph StateGraph** | 自建状态机 / LangChain AgentExecutor | `interrupt()` 原生支持人机协同；`AsyncSqliteSaver` 提供生产级 checkpoint；状态图显式建模比 AgentExecutor 的隐式循环更可控 |
| LLM 调用方式 | **原生 OpenAI SDK** | LangChain ChatOpenAI | DeepSeek 的 `reasoning_content` 是 OpenAI 协议的非标准扩展，LangChain 流式拼接不认识此字段直接丢弃；原生 SDK 保留完整控制 |
| LLM 模型 | **DeepSeek V4** | OpenAI GPT-4o / Claude | 成本（便宜 10–20 倍）、中文推理能力、`reasoning_content` 思考链可见性 |
| API Key 存储 | **RunnableConfig 内存** | 写入 AgentState | 防止密钥随 checkpoint 持久化到 SQLite；删除线程时同步从内存清除 |
| Skill 加载 | **每次从磁盘读取** | 启动时缓存 / 写入代码常量 | 热更新——调整 prompt 后立即生效无需重启；磁盘 IO 开销可忽略（每次 LLM 调用读约 3KB 文件 vs 数秒的 API 调用） |
| 子 Agent 嵌套深度 | **限制为 1** | 无限制 / 递归 | 一层分派已覆盖主场景（项目探索 + 复杂计算子任务）；更深嵌套增加调试难度且收益递减 |
| 并行子 Agent 并发 | **最多 4 worker** | 不限制 | 平衡 DeepSeek API 速率限制、本地内存占用与实际加速比（项目探索场景 3–4 个任务最优） |
| 子 Agent 步数上限 | **150 superstep（约 37 轮工具调用）** | 默认 25 | 子 Agent 整个生命周期在单次 stream 内完成，无分段预算；37 轮足以完成复杂的数据探索和分析任务 |
| 子 Agent 结果截断 | **4000 字符** | 不截断 / 更短 | 4000 字符足以传达结论、文件路径和关键数字；过短丢失信息，过长消耗主对话上下文 |
| 同一轮 tool_calls 限制 | **最多 1 个需确认** | 允许多个 | 防止 `pending_*` 互相覆盖（状态字段非列表只有一份）；多个需确认工具 LLM 可串行分轮发送 |
| high 风险脚本 | **标记高危 + 用户知情确认后执行** | 直接拒绝 | 把决策权交回用户；合法任务（如 `requests` 下载数据集）不应被技术手段阻止 |
| 中危脚本沙箱 | **注入沙箱头 wrapper** | 静态拒绝 / Docker | 运行时 hook `open()` 是 best-effort 防御而非安全边界；在 Windows 上比 Docker 更轻量且无额外依赖 |
| SSE 高频事件 | **不持久化** | 全部持久化 | 避免 SQLite 写入成为瓶颈（thinking 每秒可产数十 chunk）；重连靠 values 快照兜底（完整思考链在 `AIMessage.additional_kwargs` 中） |
| parallel_tool_calls | **关闭（False）** | 开启 | 杜绝单轮内多个需确认 tool_calls 的覆盖问题；降低单轮 token 峰值和后续处理复杂度 |
| 文件操作备份 | **执行前自动备份到 `.onerad_backup/`** | 不做备份 | move/copy 的覆盖操作不可逆；时间戳子目录实现简单快照 |
| 特征提取断点续提 | **基于 h5 缓存 + YAML hash** | 每次全量重跑 | 30 个病例提取可能需 10–30 分钟；中途失败不应从头开始 |
| 前端 busy 状态 | **完全由后端 `running` 字段驱动** | 由 `interrupt_type` 推断 | `execute_confirmed` 清除 pending 前的中间快照仍带旧 `interrupt_type`，用其推断 busy 会导致 UI 闪烁 |
| 前端乐观更新 | **用户消息乐观追加到 messages，失败回滚** | 等后端确认后再显示 | 消息发送延迟需数百 ms；乐观更新消除感知延迟；冲突由后端 409（流忙碌/待确认）兜底 |

## API 参考

### Agent 端点

| 方法 | 路径 | 说明 | 响应 |
|------|------|------|------|
| `POST` | `/api/agent/threads?project_id=` | 创建新对话 | 201 `{"thread_id": "uuid"}` |
| `GET` | `/api/agent/threads?project_id=` | 列出项目的对话 | 200 `{"threads": [...]}` |
| `GET` | `/api/agent/threads/{id}` | 获取对话状态 | 200 AgentState |
| `PATCH` | `/api/agent/threads/{id}` | 重命名对话 | 200 `{"thread": {...}}` |
| `DELETE` | `/api/agent/threads/{id}` | 删除对话（含所有 checkpoints/events） | 204 |
| `POST` | `/api/agent/threads/{id}/resume` | 恢复对话（刷新 API Key） | 200 AgentState |
| `POST` | `/api/agent/threads/{id}/messages` | 发送消息（启动流式运行） | 202 `{"thread_id": "uuid"}` |
| `PUT` | `/api/agent/threads/{id}/plan` | 编辑文件操作计划 | 200 AgentState |
| `POST` | `/api/agent/threads/{id}/confirm` | 确认当前中断 | 202 `{"thread_id": "uuid"}` |
| `POST` | `/api/agent/threads/{id}/cancel` | 取消当前中断 | 202 `{"thread_id": "uuid"}` |
| `POST` | `/api/agent/threads/{id}/other` | 取消中断 + 传替代指令 | 202 `{"thread_id": "uuid"}` |
| `POST` | `/api/agent/threads/{id}/answer` | 提交选择面板答案（ask_user_choice） | 202 `{"thread_id": "uuid"}` |
| `POST` | `/api/agent/threads/{id}/stop` | 停止运行中的流（不清除对话） | 202 `{"thread_id": "uuid", "status": "stopped"}` |
| `PUT` | `/api/agent/threads/{id}/auto-approve` | 切换自动审批 | 200 `{"auto_approve": bool}` |
| `POST` | `/api/agent/threads/{id}/export` | 导出对话（md/docx） | 200 `{"path": "...", "format": "md"}` |
| `GET` | `/api/agent/threads/{id}/events` | SSE 事件流 | text/event-stream |

### 并发保护（409 场景）

| 场景 | 状态码 | 说明 |
|------|-----------|------|
| 线程已有流在运行中，再次 sendMessage | 409 | 「智能体正在处理上一条消息」 |
| 线程在中断等待确认中，sendMessage | 409 | 「当前存在待确认的操作」 |
| sendMessage 时线程已在运行中（`_start_stream` 原子检查） | 409 | 「智能体正在处理中」 |
| stop 时没有运行中的任务 | 409 | 「当前没有正在运行的任务」 |
| other 时没有待确认的操作 | 409 | 「当前没有待确认的操作」 |

## interrupt_type 完整矩阵

| interrupt_type | 触发工具 | pending 字段 | 前端面板 | 用户可编辑 | 取消时追加 HumanMessage |
|---------------|---------|-------------|---------|:---:|:---:|
| `system_command` | list_directory, find_files, get_file_info, read_yaml, read_json, read_tabular_file, update_yaml, create_json, update_json, inspect_image_spacing, convert_dicom_to_nifti, word_create, word_append | `pending_command` | CommandPanel | — | 否 |
| `file_plan` | plan_file_operations | `pending_plan` | PlanEditor | 编辑计划 | 是 |
| `python_script` | execute_python_script | `pending_script` | ScriptPanel | — | 是 |
| `radiomics_plan` | discover_radiomics_pairs | `pending_radiomics_plan` | RadiomicsPanel | 修改配对 | 是 |
| `radiomics_execution` | extract_radiomics_features | `pending_radiomics_execution` | RadiomicsPanel | — | 是 |
| `radiomics_analysis` | run_radiomics_analysis | `pending_radiomics_analysis` | RadiomicsPanel | — | 是 |
| `feature_statistics` | run_feature_statistics | `pending_feature_statistics` | RadiomicsPanel | — | 是 |
| `subagent_dispatch` | dispatch_subagent(general) | `pending_subagent` | ApprovalPanel | — | 是 |
| `user_choice` | ask_user_choice | `pending_choice` | ChoicePanel | 选择/输入答案 | 否 |

## 核心文件索引

### 后端（app/）

| 文件路径 | 职责 |
|---------|------|
| `app/agent/graph.py` | LangGraph 图结构定义（5 节点 + 2 条件边） |
| `app/agent/state.py` | AgentState TypedDict 定义 |
| `app/agent/nodes.py` | 5 个节点函数 + 子 Agent 执行 + 影像组学/分析/统计执行 + 思考链推送 |
| `app/agent/tools.py` | 约 24 个工具定义 + `build_tools()` 注册函数 |
| `app/agent/safety.py` | Sandbox 路径沙箱 + `validate_plan()` |
| `app/agent/runtime.py` | AgentRunContext 注册表（取消事件 + 线程间通信） |
| `app/agent/memory.py` | 项目长期记忆：`extract_memories()` 提取 + `build_memory_prompt()` 注入 |
| `app/api/agent.py` | REST API 端点（线程 CRUD、消息、确认/取消/停止/SSE、对话导出） |
| `app/api/sse.py` | EventBridge 发布/订阅总线 + 进度补偿 |
| `app/skills.py` | Skill 从磁盘加载 + `load_skill_bundle()` |
| `app/settings.py` | GeneralSettingsStore：全局设置（API Key、记忆开关）YAML 持久化 |
| `app/code_runner.py` | Python 脚本风险分级 + 沙箱头注入 + 执行 |
| `app/actions.py` | 文件操作计划执行（move/copy/rename/mkdir + 自动备份） |
| `app/radiomics_discovery.py` | 图像/mask 自动配对发现 |
| `app/dicom_convert.py` | DICOM 序列扫描（SimpleITK/GDCM，按 SeriesInstanceUID 分组）+ 批量转 .nii.gz |
| `app/radiomics_analysis.py` | LASSO + 逻辑回归分析 + `inspect_analysis_inputs()` + 复跑脚本生成 |
| `app/feature_statistics.py` | 特征分组统计（t 检验 + MWU）+ docx_style 学术格式报告 |
| `app/feature.py` | FeatureAgent 批量 PyRadiomics 特征提取（含断点续提） |
| `app/analysis.py` | 交叉验证引擎：逐折 LASSO 筛选 + 逻辑回归 + SHAP 可解释性分析 |
| `app/interpretation.py` | LLM 结果解读：`build_summary()` 聚合 → `interpret()` 调 LLM → `apply_to_reports()` 注入 |
| `app/clinical.py` | 临床表列名智能识别 + 中文列名 LLM 翻译为英文 |
| `app/report.py` | ReportAgent：生成中文学术格式 Word 报告（含解读注入） |
| `app/curves.py` | ROC/校准/DCA 曲线 + SHAP beeswarm/bar 图绘制 |
| `app/word_document.py` / `app/docx_style.py` | Word 文档操作 / 中文学术排版规范 |
| `app/conversation_export.py` | 对话导出为 Markdown/Word 文档 |
| `app/projects.py` | ProjectStore SQLite 管理（项目/线程/记忆/SSE 事件表） |
| `app/llm.py` | LLM 客户端封装 + 标题生成 + JSON 模式调用 |
| `app/image_spacing.py` | 影像 spacing 分布检测（`inspect_spacing`），为 resampledPixelSpacing 提供依据 |
| `app/cir_features.py` | 单例 PyRadiomics 特征提取（`cir_get_features`），由 FeatureAgent 调用 |
| `app/metrics.py` | 评估指标计算，由交叉验证引擎调用 |
| `app/api/__init__.py` | `create_app()` 装配：lifespan、路由注册、前端静态托管 |
| `app/api/deps.py` | FastAPI 依赖注入（`get_project_store` 等） |
| `app/api/filesystem.py` | 只读文件系统浏览（创建项目的路径选择器） |
| `reference_code/legacy_fs/` | 旧版目录列举接口 `fs.py`/`fs.ts`（已被 filesystem 取代，2026-07 移出主应用，仅作参考） |
| `app/api/runs.py` | 离线管线运行记录查询 |
| `main.py` | 入口：无参数启动 FastAPI 服务；带 `--image-dir`/`--feature-csv` 走 CLI 离线分析管线 |
| `app/orchestrator.py` | CLI 离线分析管线编排（`register_default_handlers`） |
| `app/direct_analysis.py` | CLI 直接分析入口：从特征 CSV + 临床表直接建模 |
| `app/discovery.py` / `app/qc.py` / `app/utils.py` | CLI 管线配对发现 / 质量控制 / 参数解析辅助（与 Agent 侧并行的旧实现） |

### Skills 与前端

| 文件路径 | 职责 |
|---------|------|
| `skills/agent-core/SKILL.md` | Agent 核心行为 System Prompt |
| `skills/radiomics-workflow/SKILL.md` | 影像组学工作流 System Prompt |
| `skills/word-report/SKILL.md` | Word 文档格式规范 + 工具使用指引 |
| `skills/result-interpretation/SKILL.md` | 结果解读三段式 prompt |
| `skills/clinical-columns/SKILL.md` | 临床表列名识别 |
| `skills/report-writing/SKILL.md` | Word 报告方法学描述润色 |
| `skills/thread-title/SKILL.md` | 对话标题生成 |
| `frontend/src/stores/agent.ts` | Pinia Agent Store（状态管理 + API 调用 + SSE 消费） |
| `frontend/src/api/agent.ts` | 前端 Agent API 客户端 + TypeScript 类型 + SSE 连接 |
| `frontend/src/views/SettingsView.vue` | 设置页面（API Key 配置 + 长期记忆开关） |
| `frontend/src/components/AgentChat.vue` | 主聊天界面 |
| `frontend/src/components/ApprovalPanel.vue` | 通用审批面板 |
| `frontend/src/components/PlanEditor.vue` | 文件操作计划编辑器 |
| `frontend/src/components/ScriptPanel.vue` | 脚本审批面板 |
| `frontend/src/components/RadiomicsPanel.vue` | 影像组学审批面板 |
| `frontend/src/components/TodoPanel.vue` | 右侧步骤进度面板 |
| `frontend/src/components/ChoicePanel.vue` | ask_user_choice 结构化提问面板 |
| `frontend/src/components/CommandPanel.vue` | system_command 类操作审批面板 |
| `frontend/src/components/SubagentPanel.vue` | 子 Agent 并行状态面板 |

## 向后兼容约定

- `AgentState.api_key` 标记为 `NotRequired`：新线程不再写入此字段，但旧 checkpoint 可能仍有值。`_resolve_api_key` 的优先级：`configurable` → `state` → 环境变量
- `AgentState.model` 写入受支持模型名；`_resolve_model` 对不在 `DEEPSEEK_MODELS` 中的值回退到默认模型（`deepseek-v4-flash`）
- 取消操作时的 HumanMessage 追加只针对重操作类型（`file_plan`/`python_script`/`radiomics_*`/`feature_statistics`/`subagent_dispatch`），简单查询不追加
- `executed: True` 注入：对 dict 结果做键注入保留原结构，对非 dict 结果包裹为 `{"executed": True, "results": ...}`
- `/stop` 的 checkpoint 清理：清除残留 `interrupt_type` 后，若 snapshot 仍含未应答 tool_calls，为每个缺失 id 补 ToolMessage（保证后续 LLM 调用不 400）

## 术语对照

| 中文 | 英文（代码中） | 说明 |
|------|--------------|------|
| 对话/线程 | thread | LangGraph 的一个 checkpoint 会话 |
| 中断 | interrupt | LangGraph `interrupt()` 挂起图执行 |
| 工具调用 | tool_call | LLM function calling 的一次调用 |
| 子 Agent | subagent | `dispatch_subagent` 分派的独立执行单元 |
| 审批面板 | ApprovalPanel | 中断时前端展示的确认界面 |
| 思考链 | thinking / reasoning_content | DeepSeek 推理模型的思考过程 |
| 断点续提 | resume | 特征提取中已完成的 h5 缓存跳过重提 |
| 自动审批 | auto_approve | 跳过 human_review，直接执行 |
