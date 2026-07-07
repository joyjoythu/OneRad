import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.projects import ProjectStore
from app.ui import create_ui


@pytest.fixture
def isolated_store():
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp)


def test_create_project_flow(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    project = store.create_project("TestProj", str(Path(isolated_store) / "TestProj"), "desc")
    loaded = store.load_project(project["id"])
    assert loaded["name"] == "TestProj"
    assert loaded["analysis"]["output_dir"] == "./outputs"


def test_create_ui_returns_blocks():
    demo = create_ui()
    assert demo is not None
    assert hasattr(demo, "launch")


def test_ui_contains_brand_header():
    demo = create_ui()
    config = demo.get_config_file()
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]
    html_text = " ".join([h.get("props", {}).get("value", "") for h in html_blocks])
    assert "OneRad" in html_text
    assert "医学影像智能分析平台" in html_text


def test_ui_contains_key_sections():
    demo = create_ui()
    config = demo.get_config_file()
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]
    html_text = " ".join([h.get("props", {}).get("value", "") for h in html_blocks])
    assert "项目管理" in html_text
    assert "数据源" in html_text
    assert "分析配置" in html_text
    assert "AI 模型配置" in html_text
    assert "运行日志" in html_text
