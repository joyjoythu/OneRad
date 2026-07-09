import ast
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


HIGH_RISK_MODULES = {
    "socket",
    "urllib",
    "urllib3",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "subprocess",
    "paramiko",
    "ctypes",
    "os",
    "shutil",
    "pathlib",
    "importlib",
}
MEDIUM_RISK_WRITE_PATTERNS = [
    r"open\s*\([^)]*,\s*[\"'][wax][\"']",
    r"open\s*\([^)]*mode\s*=\s*[\"'][wax][\"']",
]
DANGEROUS_NAMES = {"system", "popen", "exec", "eval", "rmtree", "remove", "unlink", "__import__", "getattr"}

# 字符串字面量中危险路径特征的静态检测
PATH_TRAVERSAL_PATTERN = r"['\"][^'\"]*\.\.[^'\"]*['\"]"
WINDOWS_ABS_PATH_PATTERN = r"(?i)r?['\"][a-z]:[/\\]"


def classify_risk(code: str) -> str:
    """AST 静态扫描脚本风险等级。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "high"

    # 静态字符串检测：直接访问 __builtins__ 或使用 __import__ 字符串均视为高危
    if "__builtins__" in code:
        return "high"
    if "__import__" in code:
        return "high"

    import_map: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                import_map[local] = alias.name
                top = alias.name.split(".")[0]
                if top in HIGH_RISK_MODULES:
                    return "high"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                import_map[local] = module
            top = module.split(".")[0]
            if top in HIGH_RISK_MODULES:
                return "high"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in {"exec", "eval"}:
                    return "high"
                if func.id == "__import__":
                    return "high"
                source = import_map.get(func.id)
                if source:
                    top = source.split(".")[0]
                    if top in HIGH_RISK_MODULES and func.id in DANGEROUS_NAMES:
                        return "high"
            elif isinstance(func, ast.Attribute):
                if func.attr in DANGEROUS_NAMES:
                    return "high"

    # 检测 .. 父目录引用、Unix 绝对路径与 Windows 绝对路径（高危路径特征优先于写操作）
    if re.search(r"['\"]/[^'\"\n]+['\"]", code):
        return "high"
    if re.search(PATH_TRAVERSAL_PATTERN, code):
        return "high"
    if re.search(WINDOWS_ABS_PATH_PATTERN, code):
        return "high"

    # 检测写操作
    for pat in MEDIUM_RISK_WRITE_PATTERNS:
        if re.search(pat, code):
            return "medium"

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


SANDBOX_HEADER_TEMPLATE = """import builtins, io, os
_PROJECT_ROOT = os.path.abspath({project_path!r})
_orig_open = builtins.open
_io_open = io.open
def _safe_open(file, *args, **kwargs):
    try:
        path_str = os.fsdecode(os.fspath(file))
        path = os.path.abspath(os.path.join(_PROJECT_ROOT, path_str))
    except Exception:
        return _orig_open(file, *args, **kwargs)
    if not path.startswith(_PROJECT_ROOT + os.sep):
        raise PermissionError(f"Access outside project sandbox: {{file!r}}")
    return _orig_open(file, *args, **kwargs)
builtins.open = _safe_open
io.open = _safe_open
"""


def execute_script_if_safe(meta: Dict[str, Any], project_path: str) -> Dict[str, Any]:
    if meta.get("risk_level") == "high":
        return {"error": "脚本被判定为高风险，拒绝执行", "risk_level": "high", "success": False}

    script_path = meta["script_path"]
    if meta.get("risk_level") in {"low", "medium"}:
        original_code = Path(script_path).read_text(encoding="utf-8")
        sandbox_header = SANDBOX_HEADER_TEMPLATE.format(project_path=project_path)
        Path(script_path).write_text(sandbox_header + "\n" + original_code, encoding="utf-8")

    return run_script(script_path, project_path)


def _short_id(length: int = 6) -> str:
    return uuid.uuid4().hex[:length]
