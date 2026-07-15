import json
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


def test_execute_python_script_rejects_high_risk(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "import os\nos.system('ls')"
    result = tools["execute_python_script"].invoke(
        {"description": "high risk test", "code": code}
    )
    data = json.loads(result)
    assert data["error"] == "脚本被判定为高风险，拒绝执行"
    assert data["risk_level"] == "high"


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


def test_extract_radiomics_features_returns_error_for_path_escape(tmp_path):
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
