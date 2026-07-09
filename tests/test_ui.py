import shutil
import sys
import tempfile
from pathlib import Path

import gradio as gr
import pandas as pd
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

    # 使用原生 Button 列表：查找 value 中包含项目名称的按钮
    buttons = [c for c in config.get("components", []) if c.get("type") == "button"]
    values = [b.get("props", {}).get("value", "") for b in buttons]
    assert any("TestProj" in str(v) for v in values)


def test_project_list_html_reflects_deletion(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    project = store.create_project("ToDelete", str(Path(isolated_store) / "ToDelete"), "")
    html_text = project_list_html(store.list_projects(), "")
    assert "ToDelete" in html_text

    store.delete_project(project["id"])
    html_after = project_list_html(store.list_projects(), "")
    assert "ToDelete" not in html_after
    assert "onerad-empty-state" in html_after


def test_run_analysis_uses_cached_features_csv(tmp_path):
    """_run_analysis should bypass the image pipeline when radiomics_features.csv exists."""
    import numpy as np
    from app.ui import _run_analysis

    rng = np.random.RandomState(11)
    n = 40
    label = rng.randint(0, 2, n)
    feature_df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
    })
    for j in range(20):
        feature_df[f"original_feat_{j}"] = rng.randn(n)
    feature_df["original_feat_0"] += label * 1.5

    clinical_df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
        "Label": label,
    })

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    feature_df.to_csv(output_dir / "radiomics_features.csv", index=False)
    clinical_csv = tmp_path / "clinical.csv"
    clinical_df.to_csv(clinical_csv, index=False)

    logs, report_path = _run_analysis(
        img_dir="./nonexistent_images",
        clinical=str(clinical_csv),
        out_dir=str(output_dir),
        mod="auto",
        covs="",
        key=None,
        m="deepseek-v4-pro",
        yaml_path=str(tmp_path / "Params_labels.yaml"),
        max_lasso_features=20,
        n_splits=3,
    )
    assert report_path is not None
    assert "radiomics_features.csv" in logs
    assert Path(report_path).exists()
