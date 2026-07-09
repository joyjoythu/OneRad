import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage

from app.agent.safety import Sandbox, validate_plan
from app.code_runner import classify_risk, prepare_script, execute_script_if_safe


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
        snapshot = _directory_snapshot(sandbox.root)
        prompt = f"项目目录结构快照：\n{snapshot}\n\n用户需求：{instruction}"
        response = llm.invoke([SystemMessage(content=SYSTEM_PLAN_PROMPT), HumanMessage(content=prompt)])
        plan = _extract_json(response.content)
        validated = validate_plan(plan, sandbox)
        return json.dumps(validated)

    @tool
    def execute_python_script(description: str, code: str) -> str:
        """生成 Python 脚本并在项目虚拟环境中运行。中高风险脚本需确认。"""
        risk_level = classify_risk(code)
        if risk_level == "high":
            return json.dumps({"error": "脚本被判定为高风险，拒绝执行", "risk_level": "high"})
        meta = prepare_script(code, description, project_path)
        if risk_level == "medium":
            return json.dumps({"_pending_tool": "execute_python_script", "script": meta})
        result = execute_script_if_safe(meta, project_path)
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
