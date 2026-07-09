# OneRad LangGraph AI Agent 设计方案

> 文档版本：v1.0  
> 创建日期：2026-07-09  
> 关联需求：`docs/AI文件操作需求文档.md`

---

## 1. 设计目标

在 OneRad 现有 Gradio UI 中新增一个 **“AI Agent” 标签页**，基于 LangGraph 构建一个支持多轮对话、工具调用和人工确认的智能助手。

核心能力：

- **自然语言对话**：回答项目、影像组学、使用方法等问题。
- **文件操作工具**：`move | copy | rename | mkdir`（严格白名单，无 `delete`），先生成批量计划，用户确认后执行。
- **安全系统信息工具**：`list_directory | find_files | get_file_info`（只读、Python 实现），每次调用前经用户确认。
- **Python 脚本生成与执行**：Agent 可在当前项目目录内生成并运行 Python 脚本，按风险分级确认。
- **安全边界**：所有文件、脚本、命令操作只能在**当前选中的 OneRad 项目目录**内进行，禁止越界。
- **复用现有配置**：使用项目的 DeepSeek API 配置（`api_key / base_url / model`）。

---

## 2. 整体架构

新增模块保持与现有 `app/*.py` 扁平结构一致，同时把较复杂的 Agent 逻辑拆成独立包，避免 `ui.py` 继续膨胀。

```
app/
├── agent/
│   ├── __init__.py      # 对外暴露 create_agent_graph, stream_agent
│   ├── state.py         # AgentState 定义
│   ├── graph.py         # LangGraph 构建与编译
│   ├── nodes.py         # call_llm / human_review / execute_tools 节点
│   ├── tools.py         # LangChain Tool 定义
│   └── safety.py        # 沙箱校验、路径解析、命令/脚本风控
├── actions.py           # 文件操作真正执行（move/copy/rename/mkdir）+ 备份/日志
├── code_runner.py       # Python 脚本保存、风险分级、执行与输出捕获
├── ui_agent.py          # Agent 标签页的 Gradio 组件与事件绑定
└── ui.py                # 在现有布局中接入 create_agent_tab(...)
```

### 2.1 与现有系统的关系

- `ProjectStore`：提供当前项目路径、API 配置、分析配置。
- `LLMClient`：现有 OpenAI 客户端继续用于放射组学分析；Agent 内部使用 `langchain-openai.ChatOpenAI`（指向 DeepSeek `base_url`），两者共享同一套 API key/model。
- `app/actions.py`：对应需求文档中的 `app/actions.py` 规划。

---

## 3. LangGraph 状态与节点

### 3.1 AgentState

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # 对话历史（Human/AI/Tool/System）
    project_path: str                         # 当前项目目录（沙箱根）
    api_key: str
    base_url: str
    model: str

    interrupt_type: str | None                # None | "file_plan" | "system_command" | "python_script"
    pending_plan: list[dict] | None           # 待确认的文件操作计划
    pending_command: dict | None              # 待确认的系统信息命令
    pending_script: dict | None               # 待确认的 Python 脚本
    script_risk_level: str | None             # "low" | "medium" | "high"

    confirmed: bool | None                    # 用户是否确认当前中断
    tool_outputs: list[dict]                  # 已执行工具结果
    operation_log: list[dict]                 # 审计日志
```

### 3.2 状态图

```
START -> call_llm
call_llm -> should_continue
  ├─ 无 tool_calls -> END
  └─ 有 tool_calls -> human_review  [interrupt，等待用户确认]
human_review -> execute_tools       [用户确认 / 取消]
execute_tools -> call_llm           [把结果注入 messages]
```

- **`call_llm`**：绑定 tools 的 LLM 节点，调用 DeepSeek。
- **`human_review`**：调用 `langgraph.types.interrupt()`，把待确认内容抛给 UI。
- **`execute_tools`**：根据确认结果真正执行工具，生成 `ToolMessage` 返回给 LLM。

---

## 4. 工具层（Tools）

LLM 看到的统一工具列表如下：

| 工具 | 类别 | 行为 |
|---|---|---|
| `list_directory(path)` | 系统信息 | 只读，列出沙箱内目录内容 |
| `find_files(pattern, path)` | 系统信息 | 只读，在沙箱内递归搜索文件 |
| `get_file_info(path)` | 系统信息 | 只读，返回文件大小、修改时间等 |
| `plan_file_operations(instruction)` | 文件操作（规划） | 内部再调一次 LLM，返回 JSON 批量计划，**不执行** |
| `execute_file_operations(plan)` | 文件操作（执行） | 仅当 `state.confirmed=True` 时才真正执行 |
| `execute_python_script(description, code)` | 代码执行 | 保存脚本到项目目录，在 `.venv` 中运行，按风险分级确认 |

设计要点：

- 写操作（文件操作、代码执行）不会绕过确认流程：Agent 只能生成计划/代码，执行节点受状态保护。
- 系统信息工具虽然只读，也按需求走 `human_review` 确认后再执行。

---

## 5. 文件操作批量计划与执行

### 5.1 规划阶段

`plan_file_operations` 使用专用 prompt，要求 LLM 返回如下 JSON 数组：

```json
[
  {
    "action": "move",
    "source": "MRI/a.nii",
    "target": "Patient_001/a.nii",
    "reason": "按患者 ID 整理影像文件"
  }
]
```

### 5.2 校验阶段

- `app/agent/safety.py` 的 `Sandbox.resolve()` 把相对路径解析到 `project_path` 下，拒绝 `../etc`、符号链接逃逸、绝对路径越界。
- `validate_plan()` 检查 `action` 在白名单内，且 `source/target` 都在沙箱内。
- 发现目标已存在时，计划里标记 `overwrite: false`，执行阶段提示用户选择覆盖或跳过。

### 5.3 执行阶段

`app/actions.py` 提供核心函数：

```python
def execute_plan(plan: list[dict], project_path: str) -> list[dict]
```

执行逻辑：

1. 操作前把可能被覆盖的文件备份到 `<project_path>/.onerad_backup/<timestamp>/`。
2. 按顺序执行每条操作，记录时间、action、source、target、结果。
3. 失败的操作不会回滚已成功的，但会返回清晰错误列表。

---

## 6. Python 脚本生成与执行

### 6.1 脚本存放

脚本保存到当前项目目录下的隐藏工作区：

```
<project_path>/.agent_scripts/<timestamp>_<short_id>.py
```

执行完成后保留脚本，便于审计和回查。

### 6.2 执行环境

- 自动检测项目虚拟环境：
  - Windows: `<project_path>/.venv/Scripts/python.exe`
  - Linux/macOS: `<project_path>/.venv/bin/python`
- 使用 `subprocess.run([venv_python, script_path], cwd=project_path, capture_output=True, text=True, timeout=60)` 执行。
- 捕获 `stdout` / `stderr` 返回给 Agent 和 UI。

### 6.3 风险分级确认策略

| 风险等级 | 判定规则（AST 静态扫描） | 执行策略 |
|---|---|---|
| **低风险** | 只读取文件/数据，使用标准库或已安装包，无网络、无 subprocess、无写操作 | 自动执行，结果返回聊天 |
| **中风险** | 会在项目目录内创建/修改文件（如生成 CSV、图片、报告） | 必须展示脚本代码，**人工确认后执行** |
| **高风险** | 涉及网络、`subprocess`、`os.system`、`shutil.rmtree`、删除操作、绝对路径 `/` 等 | **拒绝执行**，并在聊天中说明原因 |

> 静态扫描只做快速风控，不是绝对安全；最终仍依赖沙箱边界和项目目录隔离。

### 6.4 安全限制

- 脚本只能读写当前项目目录（复用现有 `Sandbox.resolve()`）。
- 禁止访问外部网络。
- 禁止安装新包：脚本中若调用 `pip` / `uv` 安装依赖，直接拒绝。
- 执行前备份可能被覆盖的文件。
- 所有脚本内容、执行命令、输出写入审计日志。

---

## 7. 安全与沙箱

- **沙箱根目录**：当前选中项目的 `project["path"]`。
- **路径解析**：任何路径先 `Path.resolve()`，再判断是否以 `project_path` 开头；拒绝符号链接逃逸。
- **敏感路径黑名单**：系统盘根目录、用户 home 等。
- **文件操作白名单**：只允许 `move / copy / rename / mkdir`。
- **禁止 `delete`**。
- **系统命令**：不使用 `shell=True`，只用 Python 标准库实现。
- **审计日志**：写入 `<project_path>/logs/agent_operations.log`。

---

## 8. UI 集成

在 `app/ui.py` 现有布局右侧新增一个“AI Agent”标签页（与“数据源/分析配置”并列）：

- **聊天区**：`gr.Chatbot` + `gr.Textbox`，支持多轮对话。
- **计划预览面板**（默认隐藏）：
  - `gr.Dataframe` 展示 `action / source / target / reason`
  - 支持删除行、编辑 `target`
  - “确认执行” / “取消” 按钮
- **命令确认面板**（默认隐藏）：
  - 展示待执行的系统命令
  - “确认” / “取消” 按钮
- **脚本确认面板**（默认隐藏）：
  - 展示待执行的中风险 Python 脚本代码
  - “确认执行” / “取消” 按钮
- **结果/日志区**：展示执行成功/失败列表。

### 8.1 事件流

1. 用户输入 -> 调用 `graph.stream(...)`。
2. 若产生 `__interrupt__` 事件：
   - `interrupt_type == "file_plan"` -> 显示计划预览面板。
   - `interrupt_type == "system_command"` -> 显示命令确认面板。
   - `interrupt_type == "python_script"` -> 显示脚本确认面板。
3. 用户点击确认 -> 通过 `Command(resume=True)` 恢复图执行。
4. 执行结果回写到聊天记录。

为了降低 `ui.py` 的复杂度，Agent 相关组件封装在 `app/ui_agent.py` 中，通过 `create_agent_tab(store, project_id_state)` 返回组件和事件绑定。

---

## 9. 错误处理与日志

- LLM 返回非法 JSON：捕获并在聊天中说明“无法生成合法计划”。
- 路径越界或操作不在白名单：在校验阶段拒绝，向用户展示明确原因。
- 执行失败：记录具体文件和错误，聊天中展示失败清单。
- 取消确认：把取消原因作为 `ToolMessage` 返回给 Agent，Agent 可继续对话。
- 所有操作写入 `<project_path>/logs/agent_operations.log`。

---

## 10. 新增依赖

在 `requirements.txt` 中加入：

```text
langchain-core>=0.3.0
langchain-openai>=0.2.0
langgraph>=0.3.0
```

说明：

- `langchain-openai` 通过 `base_url` 指向 DeepSeek API，兼容 OpenAI 接口。
- Python 脚本风险扫描使用标准库 `ast`，无需额外依赖。

---

## 11. 测试策略

新增测试文件：

- `tests/test_sandbox.py`：路径越界、符号链接、normalize 场景。
- `tests/test_actions.py`：move/copy/rename/mkdir、备份、目标已存在。
- `tests/test_agent_tools.py`：工具函数在临时沙箱中的行为。
- `tests/test_code_runner.py`：脚本风险分级、沙箱执行、输出捕获。
- `tests/test_agent_graph.py`：用 mock LLM 验证图在“生成计划 -> 确认 -> 执行”流程中的状态转换。

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| DeepSeek function calling 兼容性 | 中 | `langchain-openai` + 自定义 `base_url`；如不支持，降级为 JSON plan + 工具描述模式 |
| Gradio 与 LangGraph interrupt 集成 | 中 | 把 `__interrupt__` 事件映射到组件显隐，用 `Command(resume=...)` 恢复 |
| Agent 生成错误路径 | 高 | 沙箱校验 + 用户确认 + 操作前备份 |
| Agent 建议删除/越界操作 | 高 | 操作白名单禁止 delete，路径必须落在项目目录内 |
| Python 脚本任意代码执行 | 高 | 项目目录沙箱、无网络、无新包安装、AST 风险分级、人工确认 |
| 大目录下计划过多 | 低 | 限制单次最大操作数，计划面板支持分页/滚动 |

---

## 13. 验收标准

1. 在 Gradio UI 中新增“AI Agent”标签页，支持与 Agent 多轮对话。
2. 用户输入“把 test 目录下的所有 .txt 文件复制到 backup 目录”，系统能生成正确的 copy 计划，并在确认后执行。
3. 系统信息命令（如列出目录）执行前必须展示并等待用户确认。
4. 中风险 Python 脚本执行前必须展示完整代码并等待用户确认；高风险脚本被拒绝执行。
5. 涉及项目目录外的路径或 `delete` 操作时，系统拒绝并给出提示。
6. 所有文件操作、命令调用、脚本执行记录到项目日志。
7. 复用现有 DeepSeek API 配置，无需额外配置。

---

## 14. 后续可扩展

- 把 OneRad 的影像组学分析流程（如 `run_direct_analysis`）封装为 Agent 可调用的工具。
- 支持更多只读系统命令（如文件哈希校验、图片预览元数据）。
- 引入 Docker 容器隔离执行高风险脚本。
