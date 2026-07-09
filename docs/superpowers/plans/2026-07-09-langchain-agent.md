# OneRad LangGraph AI Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 OneRad 现有 Gradio UI 中新增一个基于 LangGraph + DeepSeek 的 AI Agent 标签页，支持对话、文件操作（批量计划确认）、系统信息命令（逐条确认）和 Python 脚本生成执行（按风险分级确认）。

**Architecture：** 后端采用 `LangGraph` 状态机管理对话、工具调用和人工确认；所有文件/脚本操作通过 `app/agent/safety.py` 沙箱限制在当前项目目录内；UI 通过 `app/ui_agent.py` 独立模块接入 `app/ui.py`，避免主 UI 文件继续膨胀。

**Tech Stack：** Python 3.11/3.12、LangChain Core、LangChain-OpenAI（指向 DeepSeek）、LangGraph、Gradio、pytest。

---

## 文件结构

```
app/
├── agent/
│   ├── __init__.py      # create_agent_graph, build_initial_state
│   ├── state.py         # AgentState TypedDict
│   ├── safety.py        # Sandbox, validate_plan
│   ├── tools.py         # build_tools(project_path, llm)
│   ├── nodes.py         # call_llm / process_tool_calls / human_review / execute_confirmed
│   └── graph.py         # 编译 LangGraph
├── actions.py           # execute_plan 等文件操作
├── code_runner.py       # Python 脚本风险分级与执行
├── ui_agent.py          # Gradio Agent 标签页
└── ui.py                # 接入 create_agent_tab

tests/
├── test_sandbox.py
├── test_actions.py
├── test_code_runner.py
├── test_agent_tools.py
└── test_agent_graph.py
```

---

## Task 1: 添加依赖

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 添加依赖**

在 `requirements.txt` 末尾追加：

```text
# Agent
langchain-core>=0.3.0
langchain-openai>=0.2.0
langgraph>=0.3.0
```

- [ ] **Step 2: 安装到当前环境**

Run:
```bash
# 本项目 worktree 共享主仓库的 .venv
"D:/1实验室项目/AutoRadiomic-Agent/.venv/Scripts/python.exe" -m pip install -r requirements.txt
```

Expected: 安装成功，无版本冲突。

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add langchain-core, langchain-openai, langgraph for agent"
```

---

## Task 2: 实现沙箱模块 `app/agent/safety.py`（TDD）

**Files:**
- Create: `app/agent/safety.py`
- Create: `tests/test_sandbox.py`

- [ ] **Step 1: 写失败测试**

`tests/test_sandbox.py`：

```python
import pytest
from pathlib import Path
from app.agent.safety import Sandbox


def test_resolve_relative_path(tmp_path):
    sandbox = Sandbox(tmp_path)
    resolved = sandbox.resolve("sub/file.txt")
    assert resolved == (tmp_path / "sub" / "file.txt").resolve()


def test_rejects_path_outside_sandbox(tmp_path):
    sandbox = Sandbox(tmp_path)
    with pytest.raises(ValueError, match="outside project sandbox"):
        sandbox.resolve("../outside.txt")


def test_rejects_absolute_path_outside_sandbox(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    sandbox = Sandbox(root)
    with pytest.raises(ValueError, match="outside project sandbox"):
        sandbox.resolve("/etc/passwd")


def test_is_within(tmp_path):
    sandbox = Sandbox(tmp_path)
    assert sandbox.is_within("inside.txt") is True
    assert sandbox.is_within("../outside.txt") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_sandbox.py -v
```
Expected: 4 个 `ModuleNotFoundError` 或 `ImportError`。

- [ ] **Step 3: 实现最小代码**

`app/agent/safety.py`：

```python
from pathlib import Path
from typing import Union, List, Dict, Any


class Sandbox:
    """限制所有路径必须落在项目根目录内的沙箱。"""

    def __init__(self, root: Union[str, Path]):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"Sandbox root must be an existing directory: {root}")

    def resolve(self, path: Union[str, Path], must_exist: bool = False) -> Path:
        p = Path(path)
        if p.is_absolute():
            target = p.resolve()
        else:
            target = (self.root / p).resolve()

        try:
            target.relative_to(self.root)
        except ValueError:
            raise ValueError(f"Path outside project sandbox: {path}")

        if must_exist and not target.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")

        return target

    def is_within(self, path: Union[str, Path]) -> bool:
        try:
            self.resolve(path)
            return True
        except ValueError:
            return False


ALLOWED_ACTIONS = {"move", "copy", "rename", "mkdir"}


def validate_plan(plan: List[Dict[str, Any]], sandbox: Sandbox) -> List[Dict[str, Any]]:
    """校验 AI 生成的文件操作计划。"""
    if not isinstance(plan, list):
        raise ValueError("Plan must be a list")

    validated = []
    for idx, item in enumerate(plan):
        action = item.get("action")
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"Item {idx}: unsupported action '{action}'")

        source = item.get("source")
        target = item.get("target")

        if action in {"move", "copy", "rename"}:
            if not source or not target:
                raise ValueError(f"Item {idx}: '{action}' requires source and target")
            sandbox.resolve(source)
            sandbox.resolve(target)
        elif action == "mkdir":
            if not target:
                raise ValueError(f"Item {idx}: 'mkdir' requires target")
            sandbox.resolve(target)

        validated.append({
            "action": action,
            "source": source,
            "target": target,
            "reason": item.get("reason", ""),
            "overwrite": False,
        })
    return validated
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest tests/test_sandbox.py -v
```
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add app/agent/safety.py tests/test_sandbox.py
git commit -m "feat(agent): add project sandbox and plan validation"
```

---

## Task 3: 实现文件操作执行 `app/actions.py`（TDD）

**Files:**
- Create: `app/actions.py`
- Create: `tests/test_actions.py`

- [ ] **Step 1: 写失败测试**

`tests/test_actions.py`：

```python
import pytest
from pathlib import Path
from app.actions import execute_plan


def test_execute_copy_and_mkdir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")

    plan = [
        {"action": "mkdir", "target": "backup", "reason": "创建备份目录"},
        {"action": "copy", "source": "src/a.txt", "target": "backup/a.txt", "reason": "备份文件"},
    ]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is True
    assert results[1]["success"] is True
    assert (tmp_path / "backup" / "a.txt").read_text() == "hello"


def test_rejects_delete_action(tmp_path):
    plan = [{"action": "delete", "source": "x.txt", "reason": "删除"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is False


def test_target_exists_without_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("existing")
    (tmp_path / "b.txt").write_text("new")
    plan = [{"action": "copy", "source": "b.txt", "target": "a.txt", "reason": "覆盖"}]
    results = execute_plan(plan, str(tmp_path))
    assert results[0]["success"] is False
    assert "exists" in results[0]["error"].lower()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_actions.py -v
```
Expected: `ImportError` 或断言失败。

- [ ] **Step 3: 实现最小代码**

`app/actions.py`：

```python
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from app.agent.safety import Sandbox


ALLOWED_ACTIONS = {"move", "copy", "rename", "mkdir"}


def execute_plan(plan: List[Dict[str, Any]], project_path: str) -> List[Dict[str, Any]]:
    sandbox = Sandbox(project_path)
    backup_dir = _make_backup_dir(project_path)
    results = []
    for item in plan:
        results.append(_execute_one(item, sandbox, backup_dir, project_path))
    return results


def _make_backup_dir(project_path: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(project_path) / ".onerad_backup" / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _backup_file(target: Path, backup_dir: Path, project_path: str) -> None:
    rel = target.relative_to(Path(project_path))
    dest = backup_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, dest)
    else:
        shutil.copy2(target, dest)


def _execute_one(item: Dict[str, Any], sandbox: Sandbox, backup_dir: Path, project_path: str) -> Dict[str, Any]:
    action = item.get("action")
    if action not in ALLOWED_ACTIONS:
        return {"success": False, "error": f"Unsupported action: {action}", "item": item}

    try:
        if action == "mkdir":
            target = sandbox.resolve(item["target"])
            target.mkdir(parents=True, exist_ok=True)
            return {"success": True, "action": action, "target": str(target.relative_to(sandbox.root))}

        source = sandbox.resolve(item["source"], must_exist=True)
        target = sandbox.resolve(item["target"])

        if target.exists() and not item.get("overwrite"):
            return {"success": False, "error": f"Target exists: {target}", "item": item}

        if target.exists():
            _backup_file(target, backup_dir, project_path)

        if action == "move":
            shutil.move(str(source), str(target))
        elif action == "copy":
            if source.is_dir():
                shutil.copytree(str(source), str(target))
            else:
                shutil.copy2(str(source), str(target))
        elif action == "rename":
            source.rename(target)

        return {
            "success": True,
            "action": action,
            "source": str(source.relative_to(sandbox.root)),
            "target": str(target.relative_to(sandbox.root)),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "item": item}
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest tests/test_actions.py -v
```
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add app/actions.py tests/test_actions.py
git commit -m "feat(agent): add safe file action executor with backup"
```

---

## Task 4: 实现 Python 脚本执行 `app/code_runner.py`（TDD）

**Files:**
- Create: `app/code_runner.py`
- Create: `tests/test_code_runner.py`

- [ ] **Step 1: 写失败测试**

`tests/test_code_runner.py`：

```python
import pytest
import sys
from pathlib import Path
from app.code_runner import classify_risk, prepare_script, run_script, find_venv_python


def test_classify_low_risk():
    code = "print('hello')\nwith open('a.txt') as f: f.read()"
    assert classify_risk(code) == "low"


def test_classify_medium_risk_write():
    code = "with open('a.txt', 'w') as f: f.write('x')"
    assert classify_risk(code) == "medium"


def test_classify_high_risk_network():
    code = "import requests\nrequests.get('http://example.com')"
    assert classify_risk(code) == "high"


def test_prepare_and_run_low_risk_script(tmp_path, monkeypatch):
    # 模拟项目目录和 venv
    script_dir = tmp_path / ".agent_scripts"
    venv_bin = tmp_path / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv_bin.mkdir(parents=True)
    python_exe = venv_bin / ("python.exe" if sys.platform == "win32" else "python")
    python_exe.symlink_to(Path(sys.executable))

    code = "print('ok')"
    meta = prepare_script(code, "test", str(tmp_path))
    assert meta["risk_level"] == "low"
    assert Path(meta["script_path"]).exists()

    result = run_script(meta["script_path"], str(tmp_path))
    assert result["returncode"] == 0
    assert "ok" in result["stdout"]
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_code_runner.py -v
```
Expected: Import/Assertion errors。

- [ ] **Step 3: 实现最小代码**

`app/code_runner.py`：

```python
import ast
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


HIGH_RISK_MODULES = {"socket", "urllib", "http", "requests", "ftplib", "smtplib", "subprocess"}
MEDIUM_RISK_WRITE_PATTERNS = [r"open\s*\([^)]*[\"']w", r"open\s*\([^)]*[\"']a", r"open\s*\([^)]*[\"']x"]


def classify_risk(code: str) -> str:
    """AST 静态扫描脚本风险等级。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "high"

    has_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            has_import = True
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in HIGH_RISK_MODULES:
                    return "high"
        elif isinstance(node, ast.ImportFrom):
            has_import = True
            top = (node.module or "").split(".")[0]
            if top in HIGH_RISK_MODULES:
                return "high"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in {"system", "popen", "exec", "eval", "rmtree", "remove", "unlink"}:
                    return "high"
            elif isinstance(func, ast.Name) and func.id in {"exec", "eval"}:
                return "high"

    # 检测写操作
    for pat in MEDIUM_RISK_WRITE_PATTERNS:
        if re.search(pat, code):
            return "medium"

    # 检测绝对路径
    if re.search(r"['\"]/[^'\"\n]+['\"]", code):
        return "high"

    return "low"


def find_venv_python(project_path: str) -> Path:
    root = Path(project_path)
    if sys.platform == "win32":
        candidate = root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = root / ".venv" / "bin" / "python"
    if candidate.exists():
        return candidate
    # 兜底：使用当前解释器
    return Path(sys.executable)


def prepare_script(code: str, description: str, project_path: str) -> Dict[str, Any]:
    sandbox_root = Path(project_path)
    scripts_dir = sandbox_root / ".agent_scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = _short_id()
    script_path = scripts_dir / f"{ts}_{short_id}.py"
    script_path.write_text(code, encoding="utf-8")

    risk_level = classify_risk(code)
    return {
        "description": description,
        "script_path": str(script_path),
        "risk_level": risk_level,
        "created_at": ts,
    }


def run_script(script_path: str, project_path: str, timeout: int = 60) -> Dict[str, Any]:
    python_exe = find_venv_python(project_path)
    try:
        proc = subprocess.run(
            [str(python_exe), str(script_path)],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "success": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s", "success": False}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}


def _short_id(length: int = 6) -> str:
    import uuid
    return uuid.uuid4().hex[:length]
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest tests/test_code_runner.py -v
```
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add app/code_runner.py tests/test_code_runner.py
git commit -m "feat(agent): add python script risk classification and runner"
```

---

## Task 5: 实现 Agent 状态与工具 `app/agent/state.py` / `app/agent/tools.py`

**Files:**
- Create: `app/agent/state.py`
- Create: `app/agent/tools.py`
- Create: `tests/test_agent_tools.py`

- [ ] **Step 1: 实现状态定义**

`app/agent/state.py`：

```python
from typing import Annotated, TypedDict, Optional, Any, List
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    project_path: str
    api_key: str
    base_url: str
    model: str

    interrupt_type: Optional[str]                  # file_plan / system_command / python_script
    pending_plan: Optional[List[Dict[str, Any]]]
    pending_command: Optional[Dict[str, Any]]
    pending_script: Optional[Dict[str, Any]]
    script_risk_level: Optional[str]

    confirmed: Optional[bool]
    tool_outputs: Annotated[list, lambda x, y: x + y]
    operation_log: Annotated[list, lambda x, y: x + y]
```

- [ ] **Step 2: 写工具测试**

`tests/test_agent_tools.py`：

```python
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage
from app.agent.tools import build_tools
from app.agent.safety import Sandbox


def test_list_directory_tool_schema():
    fake_llm = MagicMock()
    tools = build_tools("/tmp/fake", fake_llm)
    assert "list_directory" in tools
    assert "find_files" in tools
    assert "get_file_info" in tools
    assert "plan_file_operations" in tools
    assert "execute_python_script" in tools


def test_list_directory_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["list_directory"].invoke({"path": "sub"})
    data = __import__("json").loads(result)
    assert data["_pending_tool"] == "list_directory"
```

- [ ] **Step 3: 运行测试确认失败**

Run:
```bash
pytest tests/test_agent_tools.py -v
```
Expected: `ImportError`。

- [ ] **Step 4: 实现工具模块**

`app/agent/tools.py`：

```python
import json
import os
from typing import Dict, Any, List
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage

from app.agent.safety import Sandbox, validate_plan
from app.code_runner import prepare_script, run_script


SYSTEM_PLAN_PROMPT = """你是一个医学影像项目文件整理助手。
请根据用户需求，返回一段 JSON 数组格式的操作计划。
仅允许以下 action：move、copy、rename、mkdir。严禁 delete。
所有 source/target 都应是相对于项目根目录的相对路径。

返回格式：
[
  {"action": "move", "source": "...", "target": "...", "reason": "..."}
]
"""


def build_tools(project_path: str, llm):
    sandbox = Sandbox(project_path)
    tools: Dict[str, Any] = {}

    @tool
    def list_directory(path: str) -> str:
        """列出项目目录下的内容。执行前需要用户确认。"""
        return json.dumps({"_pending_tool": "list_directory", "args": {"path": path}})

    @tool
    def find_files(pattern: str, path: str = ".") -> str:
        """在项目目录内按通配符搜索文件。执行前需要用户确认。"""
        return json.dumps({"_pending_tool": "find_files", "args": {"pattern": pattern, "path": path}})

    @tool
    def get_file_info(path: str) -> str:
        """获取文件或目录的元信息。执行前需要用户确认。"""
        return json.dumps({"_pending_tool": "get_file_info", "args": {"path": path}})

    @tool
    def plan_file_operations(instruction: str) -> str:
        """根据用户需求生成文件操作计划。仅生成计划，不实际执行。"""
        # 简单目录快照，帮助 AI 理解
        snapshot = _directory_snapshot(sandbox.root)
        prompt = f"项目目录结构快照：\n{snapshot}\n\n用户需求：{instruction}"
        response = llm.invoke([SystemMessage(content=SYSTEM_PLAN_PROMPT), HumanMessage(content=prompt)])
        plan = _extract_json(response.content)
        validated = validate_plan(plan, sandbox)
        return json.dumps(validated)

    @tool
    def execute_python_script(description: str, code: str) -> str:
        """生成 Python 脚本并在项目虚拟环境中运行。中高风险脚本需确认。"""
        meta = prepare_script(code, description, project_path)
        if meta["risk_level"] == "high":
            return json.dumps({"error": "脚本被判定为高风险，拒绝执行", "risk_level": "high"})
        if meta["risk_level"] == "medium":
            return json.dumps({"_pending_tool": "execute_python_script", "script": meta})
        # low risk: execute immediately
        result = run_script(meta["script_path"], project_path)
        return json.dumps(result)

    tools["list_directory"] = list_directory
    tools["find_files"] = find_files
    tools["get_file_info"] = get_file_info
    tools["plan_file_operations"] = plan_file_operations
    tools["execute_python_script"] = execute_python_script
    return tools


def _directory_snapshot(root: Path, max_depth: int = 2) -> str:
    lines = []
    for base, dirs, files in os.walk(root):
        depth = len(Path(base).relative_to(root).parts)
        if depth > max_depth:
            del dirs[:]
            continue
        indent = "  " * depth
        lines.append(f"{indent}{Path(base).name}/")
        for f in files[:20]:
            lines.append(f"{indent}  {f}")
    return "\n".join(lines)


def _extract_json(text: str) -> Any:
    import re
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    matches = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
    for m in matches:
        try:
            return json.loads(m.strip())
        except json.JSONDecodeError:
            continue
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return []
```

- [ ] **Step 5: 运行测试确认通过**

Run:
```bash
pytest tests/test_agent_tools.py -v
```
Expected: 2 passed。

- [ ] **Step 6: Commit**

```bash
git add app/agent/state.py app/agent/tools.py tests/test_agent_tools.py
git commit -m "feat(agent): add agent state and tool definitions"
```

---

## Task 6: 实现 LangGraph 节点与图 `app/agent/nodes.py` / `app/agent/graph.py` / `app/agent/__init__.py`（TDD）

**Files:**
- Create: `app/agent/nodes.py`
- Create: `app/agent/graph.py`
- Modify: `app/agent/__init__.py`
- Create: `tests/test_agent_graph.py`

- [ ] **Step 1: 实现节点模块**

`app/agent/nodes.py`：

```python
import json
from typing import Literal
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from app.agent.tools import build_tools
from app.agent.safety import Sandbox
from app.actions import execute_plan
from app.code_runner import run_script


def call_llm(state):
    llm = ChatOpenAI(
        api_key=state["api_key"],
        base_url=state["base_url"],
        model=state["model"],
        temperature=0.2,
    )
    tools = build_tools(state["project_path"], llm)
    model_with_tools = llm.bind_tools(list(tools.values()))
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state) -> Literal["process_tool_calls", "__end__"]:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "process_tool_calls"
    return "__end__"


def process_tool_calls(state):
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", [])
    if not tool_calls:
        return {"interrupt_type": None}

    llm = ChatOpenAI(api_key=state["api_key"], base_url=state["base_url"], model=state["model"], temperature=0.2)
    tools = build_tools(state["project_path"], llm)

    updates = {"messages": []}
    interrupt_type = None

    for tc in tool_calls:
        name = tc["name"]
        args = tc["args"]
        tool_result = tools[name].invoke(args)
        parsed = json.loads(tool_result)

        if name in {"list_directory", "find_files", "get_file_info"}:
            interrupt_type = "system_command"
            updates["pending_command"] = parsed
        elif name == "plan_file_operations":
            interrupt_type = "file_plan"
            updates["pending_plan"] = parsed
        elif name == "execute_python_script":
            if "error" in parsed:
                updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))
            elif "_pending_tool" in parsed:
                interrupt_type = "python_script"
                updates["pending_script"] = parsed["script"]
                updates["script_risk_level"] = parsed["script"]["risk_level"]
            else:
                updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))
        else:
            updates["messages"].append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))

    updates["interrupt_type"] = interrupt_type
    return updates


def route_after_process(state) -> Literal["human_review", "call_llm"]:
    return "human_review" if state.get("interrupt_type") else "call_llm"


def human_review(state):
    value = interrupt({
        "type": state["interrupt_type"],
        "plan": state.get("pending_plan"),
        "command": state.get("pending_command"),
        "script": state.get("pending_script"),
    })
    return {
        "confirmed": value.get("action") == "confirm",
        "pending_plan": value.get("plan", state.get("pending_plan")),
    }


def execute_confirmed(state):
    last = state["messages"][-1]
    tool_call_id = last.tool_calls[0]["id"] if hasattr(last, "tool_calls") and last.tool_calls else ""

    if not state.get("confirmed"):
        content = json.dumps({"cancelled": True, "reason": "用户取消了操作"})
        return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]}, state)

    itype = state["interrupt_type"]
    if itype == "file_plan":
        results = execute_plan(state["pending_plan"], state["project_path"])
    elif itype == "system_command":
        results = _run_system_command(state["pending_command"], state["project_path"])
    elif itype == "python_script":
        results = run_script(state["pending_script"]["script_path"], state["project_path"])
    else:
        results = {"error": "unknown interrupt type"}

    content = json.dumps(results)
    return _clear_interrupt({"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]}, state)


def _run_system_command(command: dict, project_path: str) -> dict:
    tool = command.get("_pending_tool") or command.get("tool")
    args = command.get("args", {})
    sandbox = Sandbox(project_path)
    try:
        if tool == "list_directory":
            target = sandbox.resolve(args["path"])
            entries = [f"{'D' if e.is_dir() else 'F'} {e.name}" for e in sorted(target.iterdir())]
            return {"tool": tool, "result": "\n".join(entries)}
        elif tool == "find_files":
            target = sandbox.resolve(args.get("path", "."))
            matches = list(target.rglob(args["pattern"]))[:100]
            return {"tool": tool, "result": [str(m.relative_to(sandbox.root)) for m in matches]}
        elif tool == "get_file_info":
            target = sandbox.resolve(args["path"], must_exist=True)
            st = target.stat()
            return {"tool": tool, "result": {"path": str(target.relative_to(sandbox.root)), "size": st.st_size, "mtime": st.st_mtime, "is_dir": target.is_dir()}}
        return {"error": f"unknown command {tool}"}
    except Exception as e:
        return {"error": str(e)}


def _clear_interrupt(updates: dict, state: dict) -> dict:
    updates.update({
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "confirmed": None,
    })
    return updates
```

- [ ] **Step 2: 实现图与初始化**

`app/agent/graph.py`：

```python
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from app.agent.state import AgentState
from app.agent.nodes import (
    call_llm,
    process_tool_calls,
    human_review,
    execute_confirmed,
    should_continue,
    route_after_process,
)


def create_agent_graph():
    builder = StateGraph(AgentState)
    builder.add_node("call_llm", call_llm)
    builder.add_node("process_tool_calls", process_tool_calls)
    builder.add_node("human_review", human_review)
    builder.add_node("execute_confirmed", execute_confirmed)

    builder.add_edge(START, "call_llm")
    builder.add_conditional_edges("call_llm", should_continue, {"process_tool_calls": "process_tool_calls", "__end__": END})
    builder.add_conditional_edges("process_tool_calls", route_after_process, {"human_review": "human_review", "call_llm": "call_llm"})
    builder.add_edge("human_review", "execute_confirmed")
    builder.add_edge("execute_confirmed", "call_llm")

    # 使用内存 checkpoint，支持 interrupt / resume
    return builder.compile(checkpointer=MemorySaver())
```

`app/agent/__init__.py`：

```python
from app.agent.graph import create_agent_graph


def build_initial_state(project: dict) -> dict:
    analysis = project.get("analysis", {})
    return {
        "messages": [],
        "project_path": project["path"],
        "api_key": analysis.get("api_key", ""),
        "base_url": "https://api.deepseek.com/v1",
        "model": analysis.get("model", "deepseek-chat"),
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "confirmed": None,
        "tool_outputs": [],
        "operation_log": [],
    }
```

- [ ] **Step 3: 写图测试**

`tests/test_agent_graph.py`：

```python
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.agent import create_agent_graph, build_initial_state


def test_graph_runs_to_end_without_tools(tmp_path):
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-chat"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="hello")]

    graph = create_agent_graph()
    with patch("app.agent.nodes.ChatOpenAI") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="Hi there")
        mock_llm_class.return_value = mock_llm

        final = graph.invoke(state)
        assert final["messages"][-1].content == "Hi there"
```

- [ ] **Step 4: 运行测试确认失败**

Run:
```bash
pytest tests/test_agent_graph.py -v
```
Expected: `ImportError` 或断言失败。

- [ ] **Step 5: 调试并运行测试确认通过**

Run:
```bash
pytest tests/test_agent_graph.py -v
```
Expected: 1 passed。

- [ ] **Step 6: Commit**

```bash
git add app/agent/__init__.py app/agent/nodes.py app/agent/graph.py tests/test_agent_graph.py
git commit -m "feat(agent): add langgraph nodes, graph and initial state"
```

---

## Task 7: 实现 Gradio Agent 标签页 `app/ui_agent.py` 并接入 `app/ui.py`

**Files:**
- Create: `app/ui_agent.py`
- Modify: `app/ui.py`

- [ ] **Step 1: 实现 `app/ui_agent.py`**

```python
import json
import uuid
from typing import Optional
import gradio as gr
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.types import Command

from app.agent import create_agent_graph, build_initial_state


def create_agent_tab(store, current_project_id_state):
    graph = create_agent_graph()

    with gr.Tab("AI Agent") as tab:
        chatbot = gr.Chatbot(label="AI Agent", height=400)
        msg_input = gr.Textbox(
            label="输入需求",
            lines=2,
            placeholder="例如：把 test 目录下的 .txt 文件复制到 backup 目录",
        )
        send_btn = gr.Button("发送")

        with gr.Column(visible=False) as plan_panel:
            gr.Markdown("### 待确认的文件操作计划")
            plan_df = gr.Dataframe(
                headers=["action", "source", "target", "reason"],
                datatype=["str", "str", "str", "str"],
                row_count=(0, "dynamic"),
                interactive=True,
                label="计划",
            )
            confirm_plan_btn = gr.Button("确认执行", variant="primary")
            cancel_plan_btn = gr.Button("取消")

        with gr.Column(visible=False) as cmd_panel:
            gr.Markdown("### 待确认的系统命令")
            cmd_md = gr.Markdown()
            confirm_cmd_btn = gr.Button("确认")
            cancel_cmd_btn = gr.Button("取消")

        with gr.Column(visible=False) as script_panel:
            gr.Markdown("### 待确认的 Python 脚本")
            script_code = gr.Code(language="python", label="脚本代码")
            confirm_script_btn = gr.Button("确认执行", variant="primary")
            cancel_script_btn = gr.Button("取消")

        agent_log = gr.Textbox(label="Agent 日志", lines=10, interactive=False)
        agent_thread_state = gr.State({"thread_id": None, "project_id": None})

    OUTPUTS = [
        agent_thread_state,
        chatbot,
        plan_panel,
        cmd_panel,
        script_panel,
        plan_df,
        cmd_md,
        script_code,
        agent_log,
    ]

    def _get_config(thread_state):
        return {"configurable": {"thread_id": thread_state["thread_id"]}}

    def _render_chat(messages):
        history = []
        for m in messages:
            if isinstance(m, HumanMessage):
                history.append([m.content, None])
            elif isinstance(m, AIMessage):
                if history and history[-1][1] is None:
                    history[-1][1] = m.content
                else:
                    history.append([None, m.content])
            elif isinstance(m, ToolMessage):
                if history:
                    history[-1][1] = (history[-1][1] or "") + f"\n\n[工具结果]\n{m.content}"
        return history

    def _panel_updates(values):
        itype = values.get("interrupt_type")
        return {
            "plan": gr.update(visible=(itype == "file_plan")),
            "cmd": gr.update(visible=(itype == "system_command")),
            "script": gr.update(visible=(itype == "python_script")),
        }

    def _panel_values(values):
        itype = values.get("interrupt_type")
        if itype == "file_plan":
            plan = values.get("pending_plan", [])
            rows = [[p["action"], p["source"], p["target"], p.get("reason", "")] for p in plan]
            return rows, "", ""
        if itype == "system_command":
            cmd = values.get("pending_command", {})
            return [], f"```json\n{json.dumps(cmd, ensure_ascii=False, indent=2)}\n```", ""
        if itype == "python_script":
            script = values.get("pending_script", {})
            path = script.get("script_path", "")
            code = ""
            try:
                with open(path, "r", encoding="utf-8") as f:
                    code = f.read()
            except Exception:
                pass
            return [], "", code
        return [], "", ""

    def _sync_from_graph(thread_state, log_msg=""):
        config = _get_config(thread_state)
        snapshot = graph.get_state(config)
        values = snapshot.values if snapshot else {}
        panels = _panel_updates(values)
        plan_rows, cmd_text, script_text = _panel_values(values)
        return (
            thread_state,
            _render_chat(values.get("messages", [])),
            panels["plan"],
            panels["cmd"],
            panels["script"],
            plan_rows,
            cmd_text,
            script_text,
            log_msg,
        )

    def on_send(msg, thread_state, project_id):
        if not project_id:
            return (
                thread_state,
                [],
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                [],
                "",
                "",
                "请先选择一个项目",
            )

        if thread_state["thread_id"] is None or thread_state["project_id"] != project_id:
            project = store.load_project(project_id)
            thread_state = {"thread_id": uuid.uuid4().hex, "project_id": project_id}
            init_state = build_initial_state(project)
            config = _get_config(thread_state)
            graph.update_state(config, init_state)
        else:
            config = _get_config(thread_state)

        try:
            for _ in graph.stream(
                {"messages": [HumanMessage(content=msg)]},
                config,
                stream_mode="values",
            ):
                pass
        except Exception as e:
            return _sync_from_graph(thread_state, f"Agent 运行出错: {e}")

        return _sync_from_graph(thread_state, "Agent 已响应")

    def _apply_plan_edit(thread_state, df_rows):
        config = _get_config(thread_state)
        snapshot = graph.get_state(config)
        values = snapshot.values if snapshot else {}
        if values.get("interrupt_type") != "file_plan":
            return
        plan = values.get("pending_plan", [])
        for row, item in zip(df_rows, plan):
            if len(row) >= 3:
                item["target"] = row[2]
        values["pending_plan"] = plan
        graph.update_state(config, values)

    def on_confirm(thread_state, df_rows=None):
        if thread_state["thread_id"] is None:
            return (
                thread_state,
                chatbot,
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                [],
                "",
                "",
                "无待确认操作",
            )
        if df_rows is not None:
            _apply_plan_edit(thread_state, df_rows)
        config = _get_config(thread_state)
        try:
            for _ in graph.stream(
                Command(resume={"action": "confirm"}),
                config,
                stream_mode="values",
            ):
                pass
        except Exception as e:
            return _sync_from_graph(thread_state, f"执行出错: {e}")
        return _sync_from_graph(thread_state, "执行完成")

    def on_cancel(thread_state):
        if thread_state["thread_id"] is None:
            return (
                thread_state,
                chatbot,
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                [],
                "",
                "",
                "无待确认操作",
            )
        config = _get_config(thread_state)
        try:
            for _ in graph.stream(
                Command(resume={"action": "cancel"}),
                config,
                stream_mode="values",
            ):
                pass
        except Exception as e:
            return _sync_from_graph(thread_state, f"取消出错: {e}")
        return _sync_from_graph(thread_state, "已取消")

    send_btn.click(
        on_send,
        inputs=[msg_input, agent_thread_state, current_project_id_state],
        outputs=OUTPUTS,
    )
    confirm_plan_btn.click(
        lambda ts, rows: on_confirm(ts, rows),
        inputs=[agent_thread_state, plan_df],
        outputs=OUTPUTS,
    )
    confirm_cmd_btn.click(on_confirm, inputs=[agent_thread_state], outputs=OUTPUTS)
    confirm_script_btn.click(on_confirm, inputs=[agent_thread_state], outputs=OUTPUTS)
    cancel_plan_btn.click(on_cancel, inputs=[agent_thread_state], outputs=OUTPUTS)
    cancel_cmd_btn.click(on_cancel, inputs=[agent_thread_state], outputs=OUTPUTS)
    cancel_script_btn.click(on_cancel, inputs=[agent_thread_state], outputs=OUTPUTS)

    return tab
```

- [ ] **Step 2: 修改 `app/ui.py` 接入标签页**

把右侧工作区改为 `gr.Tabs`，保留原分析页并新增 Agent 页。

在 `app/ui.py` 顶部添加：

```python
from app.ui_agent import create_agent_tab
```

在 `create_ui` 函数中，把原来的右侧 `with gr.Column(scale=1, elem_classes=["onerad-card"]):` 内部用 `gr.Tabs()` 包裹：

```python
with gr.Column(scale=1, elem_classes=["onerad-card"]):
    with gr.Tabs():
        with gr.Tab("影像组学分析"):
            # 把原来的 project_title、status_msg、数据源、分析配置、AI 模型配置、按钮、日志、报告全部移到这里
            ...
        create_agent_tab(store, current_project_id)
```

注意：原右侧区域的所有组件需要缩进到 `with gr.Tab("影像组学分析"):` 内。

- [ ] **Step 3: 运行 UI 启动冒烟测试**

Run:
```bash
python -c "from app.ui import create_ui; demo = create_ui(); print('UI import OK')"
```
Expected: 无报错，打印 `UI import OK`。

- [ ] **Step 4: Commit**

```bash
git add app/ui_agent.py app/ui.py
git commit -m "feat(ui): add AI Agent tab with plan/command/script confirmation"
```

---

## Task 8: 端到端验证

**Files:** 无新增，使用现有 UI 和测试。

- [ ] **Step 1: 运行全部测试**

Run:
```bash
pytest tests/test_sandbox.py tests/test_actions.py tests/test_code_runner.py tests/test_agent_tools.py tests/test_agent_graph.py -v
```
Expected: 全部通过。

- [ ] **Step 2: 启动 UI 进行手动冒烟测试**

Run:
```bash
python main.py --ui
```

在浏览器中：
1. 选择一个项目。
2. 切换到 **AI Agent** 标签页。
3. 输入“列出当前目录文件”，确认系统命令面板弹出，点击确认后应返回目录列表。
4. 输入“把 test 目录下的 .txt 文件复制到 backup 目录”，确认计划面板弹出，编辑/确认后执行。
5. 输入“写一个脚本打印 hello world”，低风险脚本应自动执行并显示输出。

- [ ] **Step 3: Commit 最终版本**

```bash
git add .
git commit -m "feat(agent): integrate LangGraph AI Agent with file ops, system commands and python script execution"
```

---

## Self-Review Checklist

### 1. Spec coverage

| 需求文档 / 设计点 | 对应 Task |
|---|---|
| 沙箱路径校验 | Task 2 |
| move/copy/rename/mkdir 白名单、备份、日志 | Task 3 |
| 系统信息命令（list/find/info） | Task 5 / Task 6 |
| 文件操作批量计划生成与确认 | Task 5 / Task 6 / Task 7 |
| Python 脚本风险分级与执行 | Task 4 / Task 5 / Task 6 / Task 7 |
| Gradio UI 标签页与确认面板 | Task 7 |
| 复用 DeepSeek API 配置 | Task 6 `call_llm`、Task 7 `build_initial_state` |
| 测试覆盖 | 每个 Task 都包含测试 |

### 2. Placeholder scan

- 无 `TBD` / `TODO` / `implement later`。
- 所有测试都包含具体断言和代码。
- 所有关键函数都给出完整实现。

### 3. Type consistency

- `AgentState` 中 `pending_plan` / `pending_command` / `pending_script` / `script_risk_level` 与各节点用法一致。
- `build_tools` 返回 `Dict[str, BaseTool]`，在 `call_llm` 和 `process_tool_calls` 中一致使用。
- `Sandbox.resolve()` 返回 `Path`，在 `actions.py`、`nodes.py`、`tools.py` 中统一使用。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-langchain-agent.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach do you prefer?
