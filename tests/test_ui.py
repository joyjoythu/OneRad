import shutil
import sys
import tempfile
from pathlib import Path

import gradio as gr
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.projects import ProjectStore
from app.ui import create_ui
from app.ui_style import CUSTOM_CSS, project_list_html


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


def _html_text(demo):
    config = demo.get_config_file()
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]
    return " ".join(h.get("props", {}).get("value", "") for h in html_blocks)


def test_create_ui_returns_blocks(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    demo = create_ui(store=store)
    assert isinstance(demo, gr.Blocks)
    config = demo.get_config_file()
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]
    assert len(html_blocks) > 0


def test_ui_contains_brand_header(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    demo = create_ui(store=store)
    html_text = _html_text(demo)
    assert "OneRad" in html_text
    assert "医学影像智能分析平台" in html_text


def test_ui_contains_key_sections(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    demo = create_ui(store=store)
    html_text = _html_text(demo)
    assert "项目" in html_text
    assert "数据源" in html_text
    assert "分析配置" in html_text
    assert "AI 模型配置" in html_text
    assert "运行日志" in html_text


def test_project_list_css_classes():
    assert ".onerad-project-list" in CUSTOM_CSS
    assert ".onerad-project-item" in CUSTOM_CSS
    assert ".onerad-project-item-active" in CUSTOM_CSS
    assert ".onerad-project-delete" in CUSTOM_CSS
    assert ".onerad-empty-state" in CUSTOM_CSS
    assert ".onerad-sidebar" in CUSTOM_CSS


def test_project_list_html_renders_projects():
    projects = [
        {"id": "proj-1", "name": "AutoRadiomic-A"},
        {"id": "proj-2", "name": "ZHY-ESWA"},
    ]
    html_text = project_list_html(projects, selected_id="proj-1")
    assert "AutoRadiomic-A" in html_text
    assert "ZHY-ESWA" in html_text
    assert 'data-project-id="proj-1"' in html_text
    assert 'data-project-id="proj-2"' in html_text
    assert "onerad-project-item-active" in html_text
    assert html_text.count("onerad-project-item-active") == 1


def test_project_list_html_escapes_name():
    malicious = "<script>alert(1)</script>"
    projects = [{"id": malicious, "name": malicious}]
    html_text = project_list_html(projects, selected_id="proj-1")
    # 项目名称与 id 都应被转义，data 属性中不应包含原始 HTML
    assert malicious not in html_text
    assert f'data-project-id="{malicious}"' not in html_text
    assert "&lt;script&gt;" in html_text
    assert "&lt;/script&gt;" in html_text


def test_project_list_html_empty_state():
    html_text = project_list_html([], selected_id="")
    assert "onerad-empty-state" in html_text
    assert "暂无项目" in html_text


def test_ui_renders_project_list(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    store.create_project("TestProj", str(Path(isolated_store) / "TestProj"), "desc")
    demo = create_ui(store=store)
    config = demo.get_config_file()

    # 使用 HTML 列表：查找 value 中包含项目名称的 HTML 组件
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]
    values = " ".join(h.get("props", {}).get("value", "") for h in html_blocks)
    assert "TestProj" in values
    # 确认项目列表 HTML 包含交互所需的 data 属性
    assert "data-project-id" in values


def test_project_list_html_reflects_deletion(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    project = store.create_project("ToDelete", str(Path(isolated_store) / "ToDelete"), "")
    html_text = project_list_html(store.list_projects(), "")
    assert "ToDelete" in html_text

    store.delete_project(project["id"])
    html_after = project_list_html(store.list_projects(), "")
    assert "ToDelete" not in html_after
    assert "onerad-empty-state" in html_after


def test_project_list_html_no_empty_placeholders():
    """HTML 项目列表只渲染实际项目，不应出现空占位行。"""
    projects = [{"id": "proj-1", "name": "OnlyOne"}]
    html_text = project_list_html(projects, "")
    # 只应有一个项目项
    assert html_text.count('class="onerad-project-item') == 1
    # 不应包含空状态
    assert "onerad-empty-state" not in html_text


def test_project_list_html_empty_state_no_placeholders():
    """无项目时显示空状态提示，而不是空占位行。"""
    html_text = project_list_html([], "")
    assert "onerad-empty-state" in html_text
    assert "暂无项目" in html_text
    assert 'class="onerad-project-item' not in html_text
