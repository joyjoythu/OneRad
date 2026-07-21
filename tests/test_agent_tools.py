import json
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage
from app.agent.tools import build_tools
from app.agent.safety import Sandbox


def test_list_directory_tool_schema(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    assert "list_directory" in tools
    assert "find_files" in tools
    assert "get_file_info" in tools
    assert "plan_file_operations" in tools
    assert "execute_python_script" in tools


def test_list_directory_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["list_directory"].invoke({"path": "sub"})
    data = json.loads(result)
    assert data["_pending_tool"] == "list_directory"


def test_execute_python_script_high_risk_returns_pending(tmp_path):
    """高危脚本不再拒绝，转为带高危标记的确认请求。"""
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "import os\nos.system('ls')"
    result = tools["execute_python_script"].invoke(
        {"description": "high risk test", "code": code}
    )
    data = json.loads(result)
    assert data["_pending_tool"] == "execute_python_script"
    assert data["script"]["risk_level"] == "high"


def test_execute_python_script_returns_medium_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "with open('test.txt', 'w') as f:\n    f.write('hello')"
    result = tools["execute_python_script"].invoke(
        {"description": "medium risk test", "code": code}
    )
    data = json.loads(result)
    assert data["_pending_tool"] == "execute_python_script"
    assert data["script"]["risk_level"] == "medium"


def test_execute_python_script_returns_low_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "print('hello from agent tool')"
    result = tools["execute_python_script"].invoke(
        {"description": "low risk test", "code": code}
    )
    data = json.loads(result)
    assert data["_pending_tool"] == "execute_python_script"
    assert data["script"]["risk_level"] == "low"


def test_execute_python_script_pending_includes_code_and_description(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "print('hello from agent tool')"
    result = tools["execute_python_script"].invoke(
        {"description": "low risk test", "code": code}
    )
    data = json.loads(result)
    assert data["script"]["code"] == code
    assert data["script"]["description"] == "low risk test"


def test_discover_radiomics_pairs_tool_exists(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    assert "discover_radiomics_pairs" in tools
    assert "extract_radiomics_features" in tools


def test_discover_radiomics_pairs_returns_pending(tmp_path):
    fake_llm = MagicMock()
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()
    (tmp_path / "images" / "case_001.nii.gz").write_text("image")
    (tmp_path / "masks" / "case_001.nii.gz").write_text("mask")
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["discover_radiomics_pairs"].invoke({})
    data = json.loads(result)
    assert data["_pending_tool"] == "discover_radiomics_pairs"


def test_discover_radiomics_pairs_returns_direct_error_without_images_dir(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["discover_radiomics_pairs"].invoke({})
    data = json.loads(result)
    assert "_pending_tool" not in data
    assert data["success"] is False
    assert "images" in data["message"].lower()


def test_discover_radiomics_pairs_error_when_masks_missing(tmp_path):
    fake_llm = MagicMock()
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "case_001.nii.gz").write_text("image")
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["discover_radiomics_pairs"].invoke({})
    data = json.loads(result)
    assert "_pending_tool" not in data
    assert data["success"] is False
    assert "masks" in data["message"].lower()


def test_extract_radiomics_features_returns_pending(tmp_path):
    fake_llm = MagicMock()
    (tmp_path / "Params_labels.yaml").write_text("dummy")
    tools = build_tools(str(tmp_path), fake_llm)
    pairs = [{"patient_id": "case_001", "image_path": "a.nii.gz", "mask_path": "b.nii.gz"}]
    result = tools["extract_radiomics_features"].invoke({"pairs": pairs})
    data = json.loads(result)
    assert data["_pending_tool"] == "extract_radiomics_features"
    assert data["meta"]["yaml_path"] == str(tmp_path / "Params_labels.yaml")
    assert data["meta"]["output_dir"] == str(tmp_path / "radiomics_features")
    assert data["meta"]["n_cases"] == 1
    assert data["meta"]["expected_outputs"] == ["radiomics_features.csv", "failed_cases.csv", "h5/*.h5"]


def test_extract_radiomics_features_with_explicit_yaml_path(tmp_path):
    fake_llm = MagicMock()
    yaml_path = tmp_path / "custom.yaml"
    yaml_path.write_text("dummy")
    tools = build_tools(str(tmp_path), fake_llm)
    pairs = [{"patient_id": "case_001", "image_path": "a.nii.gz", "mask_path": "b.nii.gz"}]
    result = tools["extract_radiomics_features"].invoke({"pairs": pairs, "yaml_path": str(yaml_path)})
    data = json.loads(result)
    assert data["_pending_tool"] == "extract_radiomics_features"
    assert data["meta"]["yaml_path"] == str(yaml_path)


def test_extract_radiomics_features_returns_error_for_empty_pairs(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["extract_radiomics_features"].invoke({"pairs": []})
    data = json.loads(result)
    assert data["success"] is False
    assert "pairs" in data["error"]


def test_extract_radiomics_features_returns_error_for_missing_yaml(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    pairs = [{"patient_id": "case_001", "image_path": "a.nii.gz", "mask_path": "b.nii.gz"}]
    result = tools["extract_radiomics_features"].invoke({"pairs": pairs})
    data = json.loads(result)
    assert data["success"] is False
    assert "YAML 配置不存在" in data["error"]


def test_extract_radiomics_features_returns_error_for_malformed_yaml(tmp_path):
    fake_llm = MagicMock()
    yaml_path = tmp_path / "Params_labels.yaml"
    yaml_path.write_text("setting:\n  binWidth: [25")  # malformed YAML
    tools = build_tools(str(tmp_path), fake_llm)
    pairs = [{"patient_id": "case_001", "image_path": "a.nii.gz", "mask_path": "b.nii.gz"}]
    result = tools["extract_radiomics_features"].invoke({"pairs": pairs})
    data = json.loads(result)
    assert "_pending_tool" not in data
    assert data["success"] is False
    assert "YAML 解析失败" in data["error"]
    fake_llm = MagicMock()
    (tmp_path / "Params_labels.yaml").write_text("dummy")
    tools = build_tools(str(tmp_path), fake_llm)
    pairs = [{"patient_id": "case_001", "image_path": "../a.nii.gz", "mask_path": "b.nii.gz"}]
    result = tools["extract_radiomics_features"].invoke({"pairs": pairs})
    data = json.loads(result)
    assert data["success"] is False
    assert "路径超出项目目录" in data["error"]


@pytest.mark.parametrize("pair,expected_key", [
    ({"patient_id": "case_001", "mask_path": "b.nii.gz"}, "image_path"),
    ({"patient_id": "case_001", "image_path": "a.nii.gz"}, "mask_path"),
])
def test_extract_radiomics_features_returns_error_for_missing_pair_keys(tmp_path, pair, expected_key):
    fake_llm = MagicMock()
    (tmp_path / "Params_labels.yaml").write_text("dummy")
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["extract_radiomics_features"].invoke({"pairs": [pair]})
    data = json.loads(result)
    assert data["success"] is False
    assert expected_key in data["error"]


def _make_analysis_project(tmp_path, n=60):
    """在项目目录内生成特征 CSV 与临床 CSV。"""
    ids = [f"P{i:03d}" for i in range(n)]
    rng = np.random.RandomState(42)
    label = np.array([i % 2 for i in range(n)])
    feat = pd.DataFrame({"patient_id": ids})
    for j in range(6):
        feat[f"original_sig_{j}"] = rng.randn(n) + label * 1.5
    feat.to_csv(tmp_path / "features.csv", index=False)
    pd.DataFrame({"patient_id": ids, "Label": label}).to_csv(
        tmp_path / "clinical.csv", index=False)


def test_run_radiomics_analysis_tool_registered(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    assert "run_radiomics_analysis" in tools


def test_run_radiomics_analysis_returns_pending_when_ready(tmp_path):
    _make_analysis_project(tmp_path)
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "features.csv", "clinical": "clinical.csv"})
    data = json.loads(result)
    assert data["_pending_tool"] == "run_radiomics_analysis"
    meta = data["meta"]
    assert meta["id_col"] == "patient_id"
    assert meta["label_col"] == "Label"
    assert meta["n_matched"] == 60
    assert meta["output_dir"] == str(tmp_path / "radiomics_analysis")


def test_run_radiomics_analysis_returns_clarification_without_pending(tmp_path):
    ids = [f"P{i:03d}" for i in range(60)]
    rng = np.random.RandomState(42)
    label = np.array([i % 2 for i in range(60)])
    feat = pd.DataFrame({"patient_id": ids})
    for j in range(6):
        feat[f"original_sig_{j}"] = rng.randn(60) + label * 1.5
    feat.to_csv(tmp_path / "features.csv", index=False)
    # 两个 0/1 列均不叫 Label → 产生歧义
    pd.DataFrame({"patient_id": ids, "group": label,
                  "group2": rng.randint(0, 2, 60)}).to_csv(
        tmp_path / "clinical.csv", index=False)
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "features.csv", "clinical": "clinical.csv"})
    data = json.loads(result)
    assert "_pending_tool" not in data
    assert data["status"] == "need_clarification"
    fields = [q["field"] for q in data["questions"]]
    assert "label_col" in fields


def test_run_radiomics_analysis_path_escape_returns_error(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "../outside.csv"})
    data = json.loads(result)
    assert data["status"] == "error"
    assert "路径超出项目目录" in data["message"]


def test_run_radiomics_analysis_passes_covariates(tmp_path):
    _make_analysis_project(tmp_path)
    # 添加 age 协变量列
    clin = pd.read_csv(tmp_path / "clinical.csv")
    clin["age"] = 50
    clin.to_csv(tmp_path / "clinical.csv", index=False)
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "features.csv", "clinical": "clinical.csv",
         "covariates": "age, nonexistent"})
    data = json.loads(result)
    assert data["_pending_tool"] == "run_radiomics_analysis"
    assert data["meta"]["covariates"] == ["age"]


def test_run_radiomics_analysis_passes_explicit_id_and_label(tmp_path):
    _make_analysis_project(tmp_path)
    clin = pd.read_csv(tmp_path / "clinical.csv")
    clin = clin.rename(columns={"patient_id": "pid", "Label": "outcome"})
    clin.to_csv(tmp_path / "clinical.csv", index=False)
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "features.csv", "clinical": "clinical.csv",
         "id_col": "pid", "label_col": "outcome"})
    data = json.loads(result)
    assert data["_pending_tool"] == "run_radiomics_analysis"
    assert data["meta"]["id_col"] == "pid"
    assert data["meta"]["label_col"] == "outcome"


def test_run_radiomics_analysis_passes_explicit_output_dir(tmp_path):
    _make_analysis_project(tmp_path)
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "features.csv", "clinical": "clinical.csv",
         "output_dir": "my_results"})
    data = json.loads(result)
    assert data["_pending_tool"] == "run_radiomics_analysis"
    assert data["meta"]["output_dir"] == str(tmp_path / "my_results")


def test_yaml_tools_registered(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    assert "read_yaml" in tools
    assert "update_yaml" in tools


def test_yaml_tools_readonly_mode(tmp_path):
    """只读模式（explore 子 agent）：read_yaml 可用，update_yaml 不注册。"""
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm, readonly=True)
    assert "read_yaml" in tools
    assert "update_yaml" not in tools


def test_read_yaml_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["read_yaml"].invoke({"path": "Params_labels.yaml", "key": "setting"})
    data = json.loads(result)
    assert data["_pending_tool"] == "read_yaml"
    assert data["args"] == {"path": "Params_labels.yaml", "key": "setting"}


def test_update_yaml_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["update_yaml"].invoke(
        {"path": "Params_labels.yaml", "updates": {"setting.binWidth": 10}})
    data = json.loads(result)
    assert data["_pending_tool"] == "update_yaml"
    assert data["args"]["updates"] == {"setting.binWidth": 10}


def test_json_tools_registered(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    assert "read_json" in tools
    assert "create_json" in tools
    assert "update_json" in tools


def test_json_tools_readonly_mode(tmp_path):
    """只读模式（explore 子 agent）：read_json 可用，create/update_json 不注册。"""
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm, readonly=True)
    assert "read_json" in tools
    assert "create_json" not in tools
    assert "update_json" not in tools


def test_read_json_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["read_json"].invoke({"path": "config.json", "key": "a.b"})
    data = json.loads(result)
    assert data["_pending_tool"] == "read_json"
    assert data["args"] == {"path": "config.json", "key": "a.b"}


def test_create_json_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["create_json"].invoke(
        {"path": "out/result.json", "content": {"a": 1}})
    data = json.loads(result)
    assert data["_pending_tool"] == "create_json"
    assert data["args"]["content"] == {"a": 1}


def test_update_json_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["update_json"].invoke(
        {"path": "config.json", "updates": {"a.b": 2}})
    data = json.loads(result)
    assert data["_pending_tool"] == "update_json"
    assert data["args"]["updates"] == {"a.b": 2}


def test_inspect_image_spacing_registered_in_all_tool_sets(tmp_path):
    fake_llm = MagicMock()
    full = build_tools(str(tmp_path), fake_llm)
    readonly = build_tools(str(tmp_path), fake_llm, readonly=True)
    assert "inspect_image_spacing" in full
    assert "inspect_image_spacing" in readonly


def test_inspect_image_spacing_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    data = json.loads(tools["inspect_image_spacing"].invoke({}))
    assert data["_pending_tool"] == "inspect_image_spacing"
    assert data["args"] == {}
    data = json.loads(tools["inspect_image_spacing"].invoke(
        {"pairs": [{"image_path": "images/a.nii.gz", "mask_path": "masks/a.nii.gz"}]}))
    assert data["args"]["pairs"][0]["image_path"] == "images/a.nii.gz"
