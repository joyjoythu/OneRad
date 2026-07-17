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
    "sys",
    "builtins",
    "asyncio",
    "multiprocessing",
    "concurrent",
    "_winapi",
    "nt",
}

# Safe standard-library modules that low-risk scripts may import without confirmation.
SAFE_MODULES = {
    "abc",
    "base64",
    "binascii",
    "calendar",
    "codecs",
    "collections",
    "contextlib",
    "copy",
    "csv",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fractions",
    "functools",
    "hashlib",
    "html",
    "inspect",
    "itertools",
    "json",
    "math",
    "numbers",
    "pprint",
    "random",
    "re",
    "statistics",
    "string",
    "textwrap",
    "time",
    "typing",
    "types",
    "uuid",
    "warnings",
}

MEDIUM_RISK_WRITE_PATTERNS = [
    r"open\s*\([^)]*,\s*[\"'][wax]b?[\"']",
    r"open\s*\([^)]*mode\s*=\s*[\"'][wax]b?[\"']",
]
DANGEROUS_NAMES = {
    "system",
    "popen",
    "exec",
    "eval",
    "rmtree",
    "remove",
    "unlink",
    "__import__",
    "getattr",
    "execv",
    "execve",
    "spawnv",
    "spawnve",
    "create_subprocess_exec",
    "create_subprocess_shell",
    "Process",
    "CreateProcess",
    "load_module",
    "exec_module",
    "run",
}

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
    risk = "low"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                import_map[local] = alias.name
                top = alias.name.split(".")[0]
                if top in HIGH_RISK_MODULES:
                    return "high"
                if top not in SAFE_MODULES:
                    risk = "medium"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                import_map[local] = module
            top = module.split(".")[0]
            if top in HIGH_RISK_MODULES:
                return "high"
            if top and top not in SAFE_MODULES:
                risk = "medium"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in {"exec", "eval"}:
                    return "high"
                if func.id == "__import__":
                    return "high"
                if func.id in DANGEROUS_NAMES:
                    return "high"
                source = import_map.get(func.id)
                if source:
                    top = source.split(".")[0]
                    if top in HIGH_RISK_MODULES and func.id in DANGEROUS_NAMES:
                        return "high"
            elif isinstance(func, ast.Attribute):
                if func.attr in DANGEROUS_NAMES:
                    return "high"
        elif isinstance(node, ast.Attribute):
            if node.attr in DANGEROUS_NAMES:
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

    return risk


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


def _slugify_description(description: str, max_length: int = 40) -> str:
    """把脚本用途描述转成合法文件名片段：保留中文，非法字符与空白转为下划线。"""
    slug = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", description)
    slug = re.sub(r"\s+", "_", slug).strip("_. ")
    return slug[:max_length].rstrip("_.") or "script"


def prepare_script(code: str, description: str, project_path: str) -> Dict[str, Any]:
    sandbox_root = Path(project_path)
    # agent_scripts 不带点号前缀：Windows 资源管理器默认可见，方便用户直接查看。
    scripts_dir = sandbox_root / "agent_scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify_description(description)
    script_path = scripts_dir / f"{slug}_{ts}.py"
    if script_path.exists():
        # 同秒同描述：追加短 id 防覆盖。
        script_path = scripts_dir / f"{slug}_{ts}_{_short_id()}.py"
    script_path.write_text(code, encoding="utf-8")

    risk_level = classify_risk(code)
    return {
        "description": description,
        "script_path": str(script_path),
        "risk_level": risk_level,
        "created_at": ts,
        "code": code,
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


SANDBOX_HEADER_TEMPLATE = """# Defense-in-depth sandbox header for medium-risk scripts.
# In-process sandboxing is best-effort and not a security boundary on Windows.
import builtins as _b, io as _io, os as _os
_PROJECT_ROOT = _os.path.abspath({project_path!r})
_orig_open = _b.open
_io_open = _io.open

def _make_safe_open(project_root, orig_open, os_mod, io_open):
    def _safe_open(file, *args, **kwargs):
        try:
            path_str = os_mod.fsdecode(os_mod.fspath(file))
            path = os_mod.path.abspath(os_mod.path.join(project_root, path_str))
        except Exception:
            return orig_open(file, *args, **kwargs)
        if not path.startswith(project_root + os_mod.sep):
            raise PermissionError(f"Access outside project sandbox: {{file!r}}")
        return orig_open(file, *args, **kwargs)
    return _safe_open

_safe_open = _make_safe_open(_PROJECT_ROOT, _orig_open, _os, _io_open)
_b.open = _safe_open
_io.open = _safe_open
del _b, _io, _os, _PROJECT_ROOT, _orig_open, _io_open, _make_safe_open, _safe_open
"""


def execute_script_if_safe(meta: Dict[str, Any], project_path: str) -> Dict[str, Any]:
    risk_level = meta.get("risk_level")
    if risk_level == "high":
        return {"error": "脚本被判定为高风险，拒绝执行", "risk_level": "high", "success": False}

    script_path = Path(meta["script_path"])

    if risk_level == "medium":
        # 仅对中危脚本注入沙箱头；通过临时副本运行，不修改原始脚本文件。
        scripts_dir = script_path.parent
        wrapped_path = scripts_dir / f"{script_path.stem}.wrapped_{_short_id()}.py"
        original_code = script_path.read_text(encoding="utf-8")
        sandbox_header = SANDBOX_HEADER_TEMPLATE.format(project_path=project_path)
        wrapped_path.write_text(sandbox_header + "\n" + original_code, encoding="utf-8")
        try:
            return run_script(str(wrapped_path), project_path)
        finally:
            try:
                wrapped_path.unlink(missing_ok=True)
            except Exception:
                pass

    # 低危脚本直接运行原始文件，不注入沙箱头。
    return run_script(str(script_path), project_path)


def _short_id(length: int = 6) -> str:
    return uuid.uuid4().hex[:length]
