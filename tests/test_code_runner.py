import pytest
import sys
from pathlib import Path
from app.code_runner import classify_risk, prepare_script, run_script, find_venv_python, execute_script_if_safe


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
    # Windows 未开启开发者模式时无法创建符号链接，直接 patch 返回当前解释器
    monkeypatch.setattr(
        "app.code_runner.find_venv_python", lambda project_path: Path(sys.executable)
    )

    code = "print('ok')"
    meta = prepare_script(code, "test", str(tmp_path))
    assert meta["risk_level"] == "low"
    assert Path(meta["script_path"]).exists()

    result = run_script(meta["script_path"], str(tmp_path))
    assert result["returncode"] == 0
    assert "ok" in result["stdout"]


def test_classify_high_risk_from_import():
    code = "from os import system\nsystem('x')"
    assert classify_risk(code) == "high"


def test_classify_high_risk_from_import_alias():
    code = "from shutil import rmtree as rm\nrm('x')"
    assert classify_risk(code) == "high"


def test_classify_syntax_error_is_high():
    code = "def foo(\n    print('missing')"
    assert classify_risk(code) == "high"


def test_execute_script_if_safe_blocks_high_risk():
    meta = {"risk_level": "high", "script_path": "/tmp/fake.py"}
    result = execute_script_if_safe(meta, "/tmp")
    assert result["success"] is False
    assert result["risk_level"] == "high"
    assert "拒绝执行" in result["error"]


def test_classify_pathlib_is_high():
    assert classify_risk("import pathlib") == "high"
    assert classify_risk("from pathlib import Path") == "high"


def test_classify_parent_reference_is_high():
    assert classify_risk("open('../outside.txt', 'w')") == "high"
    assert classify_risk("with open('sub/../../escape.txt') as f: pass") == "high"


def test_classify_windows_absolute_path_is_high():
    assert classify_risk(r"open('C:\\Users\\x.txt', 'w')") == "high"
    assert classify_risk(r"open(r'C:\\Users\\x.txt', 'w')") == "high"
    assert classify_risk("open('C:/Users/x.txt', 'w')") == "high"


def test_run_script_blocks_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.code_runner.find_venv_python", lambda project_path: Path(sys.executable)
    )
    code = "open('../outside.txt', 'w').write('x')"
    meta = prepare_script(code, "escape", str(tmp_path))
    assert meta["risk_level"] == "high"
    result = execute_script_if_safe(meta, str(tmp_path))
    assert result["success"] is False
    assert "拒绝执行" in result["error"]


def test_run_script_allows_in_project_write(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.code_runner.find_venv_python", lambda project_path: Path(sys.executable)
    )
    (tmp_path / "sub").mkdir()
    code = "open('sub/a.txt', 'w').write('hello')"
    meta = prepare_script(code, "in-project write", str(tmp_path))
    assert meta["risk_level"] == "medium"
    result = execute_script_if_safe(meta, str(tmp_path))
    assert result["success"] is True
    assert (tmp_path / "sub" / "a.txt").read_text(encoding="utf-8") == "hello"


def test_classify_dynamic_import_is_high():
    code = "__import__('os').system('echo x')"
    assert classify_risk(code) == "high"


def test_run_script_blocks_bytes_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.code_runner.find_venv_python", lambda project_path: Path(sys.executable)
    )
    # 动态构造 bytes 路径，避免静态规则命中字面量 ".."
    code = (
        "parts = bytes([ord('.'), ord('.'), ord('/'), ord('e'), ord('s'), ord('c'), "
        "ord('a'), ord('p'), ord('e'), ord('.'), ord('t'), ord('x'), ord('t')])\n"
        "open(parts, 'wb').write(b'x')"
    )
    meta = prepare_script(code, "bytes escape", str(tmp_path))
    assert meta["risk_level"] == "low"
    result = execute_script_if_safe(meta, str(tmp_path))
    assert result["success"] is False
    assert "PermissionError" in result["stderr"]


def test_run_script_blocks_dynamic_pathlib(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.code_runner.find_venv_python", lambda project_path: Path(sys.executable)
    )
    code = "__import__('pathlib').Path('..').resolve()"
    meta = prepare_script(code, "dynamic pathlib", str(tmp_path))
    # 动态 __import__ 会被分类为高危，直接拒绝
    assert meta["risk_level"] == "high"
    result = execute_script_if_safe(meta, str(tmp_path))
    assert result["success"] is False
    assert "拒绝执行" in result["error"]
