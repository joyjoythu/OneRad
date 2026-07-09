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
