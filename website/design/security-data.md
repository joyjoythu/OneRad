# 安全与数据支撑

## 安全设计

### 路径沙箱

`app/agent/safety.py` 的 Sandbox 类是**所有文件系统访问的唯一入口**：

```python
class Sandbox:
    def __init__(self, root: str):
        self.root = Path(root).resolve()      # 必须是已存在目录

    def resolve(self, path, must_exist=False):
        target = (self.root / path).resolve()  # 相对路径从 root 起算
        target.relative_to(self.root)          # 越界抛 ValueError
        if must_exist and not target.exists():
            raise FileNotFoundError(...)
        return target
```

所有工具函数在访问文件系统前必须通过 `sandbox.resolve()`。`execute_confirmed` 中有专门的 `PathEscapeError` 捕获（转义错误 → 返回 `{"success": False, "error": "路径超出项目目录"}`）。

### 确认-执行分离

传统 Agent 工具设计是「LLM 调用 → 工具函数直接执行 → 返回结果」；OneRad 的工具设计是两层：LLM 调用 → 工具函数校验参数 → 返回 `{"_pending_tool": ..., 参数}` → `process_tool_calls` 识别为需确认 → `human_review` / `auto_confirm` → `execute_confirmed` 实际执行。详见 [人机协同机制](/design/human-loop#确认-执行分离)。

### 纵深防御链

安全机制不是单点防御，而是**五层递进的纵深防御**：

1. **System Prompt**（agent-core SKILL.md）：告知 LLM 尊重每个确认步骤、沙箱边界、schema 约束和风险决策
2. **工具函数参数校验**：`extract_radiomics_features` 校验 YAML 存在与沙箱路径；`plan_file_operations` 的 `validate_plan()` 限制四种操作；`execute_python_script` 的 `classify_risk()` AST 静态扫描
3. **process_tool_calls 确认拦截**：所有副作用工具必须通过 human_review/auto_confirm
4. **execute_confirmed 运行时沙箱**：`Sandbox.resolve()` 路径解析；中危脚本注入沙箱头（运行时 hook `open()`）
5. **操作系统层**：Docker 容器隔离

## 数据库设计

### SQLite 表结构

项目与对话在同一个 SQLite 文件（`~/.onerad/projects.db` 或自定义路径），由 ProjectStore 管理；LangGraph checkpoint 由 AsyncSqliteSaver 管理（内部表 `checkpoint`、`checkpoint_blobs`、`checkpoint_writes`）：

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,          -- UUID
    name TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,    -- 项目根目录绝对路径
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE threads (
    id TEXT PRIMARY KEY,          -- UUID (即 LangGraph thread_id)
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE sse_events (              -- SSE 事件持久化
    scope TEXT NOT NULL,            -- "agent" | "pipeline"
    scope_id TEXT NOT NULL,         -- thread_id
    event_id INTEGER NOT NULL,
    data TEXT NOT NULL,             -- JSON 字符串
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, scope_id, event_id)
);

CREATE TABLE memories (                -- 项目长期记忆
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category TEXT NOT NULL,  -- clinical | decision | finding | preference | general
    fact TEXT NOT NULL,             -- 一句话事实
    created_at TEXT NOT NULL
);
CREATE INDEX idx_memories_project ON memories(project_id, created_at DESC);
```

### checkpoint 与 thread 的关系

- **thread 表**（ProjectStore）：存储对话元数据（标题、项目归属、时间戳）
- **checkpoint 表**（AsyncSqliteSaver）：存储 LangGraph 的完整状态快照（messages、state 字段）
- **sse_events 表**（ProjectStore）：存储 SSE 事件用于重连回放

三者通过 `thread_id` 关联。删除线程时需同时清理三处（见 `delete_thread` 端点）。

## 项目长期记忆

项目记忆系统在项目粒度上跨线程共享已知事实（提取 / 注入 / 五类记忆 / 全局开关），详见 [Skills 与项目记忆](/design/skills-memory#项目长期记忆)。

## 对话导出

对话导出的核心目的是**方便用户反馈 bug**：当智能体行为异常、工具调用出错或分析结果不符合预期时，用户可将完整对话（含工具调用参数、思考链、工具返回结果）导出为 Markdown 或 Word 文档，直接发送给开发人员排查。导出的文档包含用户消息、助手回复、思考过程、每次工具调用的参数与返回值，开发人员无需复现操作即可定位问题。

- 导出文件写入项目目录下的 `conversation_exports/` 子目录
- **Markdown**：对话呈层级结构（用户/助手为 Heading 2，工具结果为 Heading 3 + 代码块，思考过程为引用格式）
- **Word**：使用 python-docx 直接构建，思考过程以斜体区分，工具调用/结果以 Consolas 等宽字体呈现
- API 端点：`POST /api/agent/threads/{id}/export`，接受 `{"format": "md"|"docx"}`；文件名形如 `对话_<标题>_<时间戳>`
