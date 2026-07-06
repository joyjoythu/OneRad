import os
import tempfile
from io import BytesIO
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.clinical import ClinicalAgent


def _make_mock_llm(result):
    """Return a mock LLM client that returns *result* as JSON."""
    mock_llm = MagicMock()
    mock_llm.call.return_value = "unused"
    mock_llm._extract_json.return_value = result
    return mock_llm


def test_clinical_agent_basic():
    df = pd.DataFrame({
        "PatientID": ["P001", "P002"],
        "Age": [50, 60],
        "Sex": ["F", "M"],
        "Label": [0, 1],
    })
    buf = BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    mock_llm = _make_mock_llm(
        {"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age", "Sex"]}
    )
    agent = ClinicalAgent(llm_client=mock_llm)
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(buf.getvalue())
        path = f.name
    try:
        result = agent.run(path)
    finally:
        os.unlink(path)

    assert result["success"] is True
    assert result["id_col"] == "PatientID"
    assert result["label_col"] == "Label"
    assert result["feature_cols"] == ["Age", "Sex"]
    assert result["id_dtype"] == "str"
    assert result["n_samples"] == 2


def test_clinical_agent_missing_file():
    agent = ClinicalAgent(llm_client=_make_mock_llm({}))
    result = agent.run("/nonexistent/path/file.csv")
    assert result["success"] is False
    assert "文件不存在" in result["message"]


def test_clinical_agent_unsupported_extension(temp_dir):
    path = temp_dir / "data.txt"
    path.write_text("a,b\n1,2\n")
    agent = ClinicalAgent(llm_client=_make_mock_llm({}))
    result = agent.run(str(path))
    assert result["success"] is False
    assert "不支持的格式" in result["message"]


@pytest.mark.parametrize("df", [
    pd.DataFrame(),
    pd.DataFrame({"PatientID": ["P001"]}),
])
def test_clinical_agent_empty_or_too_few_columns(df, temp_dir):
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)
    agent = ClinicalAgent(llm_client=_make_mock_llm({}))
    result = agent.run(str(path))
    assert result["success"] is False
    # Empty file may fail at parse time; either message is acceptable.
    assert "表格为空或列数不足" in result["message"] or "读取表格失败" in result["message"]


def test_clinical_agent_no_llm_client(temp_dir):
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)
    agent = ClinicalAgent(llm_client=None)
    result = agent.run(str(path))
    assert result["success"] is False
    assert "未配置 LLM" in result["message"]


def test_clinical_agent_llm_json_failure(temp_dir):
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)

    mock_llm = MagicMock()
    mock_llm.call.return_value = "not valid json"
    mock_llm._extract_json.return_value = None

    agent = ClinicalAgent(llm_client=mock_llm, max_retries=1)
    result = agent.run(str(path))
    assert result["success"] is False
    assert "LLM 列名识别失败" in result["message"]
    # first attempt + one retry
    assert mock_llm._extract_json.call_count == 2


@pytest.mark.parametrize("field,bad_value", [
    ("id_col", "MissingID"),
    ("label_col", "MissingLabel"),
])
def test_clinical_agent_missing_required_column(temp_dir, field, bad_value):
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)

    result = {
        "id_col": "PatientID",
        "label_col": "Label",
        "feature_cols": ["Age"],
    }
    result[field] = bad_value
    agent = ClinicalAgent(llm_client=_make_mock_llm(result))
    result = agent.run(str(path))
    assert result["success"] is False
    assert "不存在" in result["message"]


def test_clinical_agent_missing_feature_columns(temp_dir):
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)

    mock_llm = _make_mock_llm({
        "id_col": "PatientID",
        "label_col": "Label",
        "feature_cols": ["MissingFeature"],
    })
    agent = ClinicalAgent(llm_client=mock_llm)
    result = agent.run(str(path))
    assert result["success"] is False
    assert "未识别到有效临床特征列" in result["message"]


@pytest.mark.parametrize("labels", [
    [0, 2],
    ["yes", "no"],
    [True, "yes"],
])
def test_clinical_agent_invalid_label_values(temp_dir, labels):
    df = pd.DataFrame({
        "PatientID": [f"P{i:03d}" for i in range(len(labels))],
        "Age": list(range(len(labels))),
        "Label": labels,
    })
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)

    agent = ClinicalAgent(llm_client=_make_mock_llm({
        "id_col": "PatientID",
        "label_col": "Label",
        "feature_cols": ["Age"],
    }))
    result = agent.run(str(path))
    assert result["success"] is False
    assert "值域非 0/1" in result["message"]


def test_clinical_agent_label_all_missing(temp_dir):
    df = pd.DataFrame({
        "PatientID": ["P001", "P002"],
        "Age": [50, 60],
        "Label": [None, None],
    })
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)

    agent = ClinicalAgent(llm_client=_make_mock_llm({
        "id_col": "PatientID",
        "label_col": "Label",
        "feature_cols": ["Age"],
    }))
    result = agent.run(str(path))
    assert result["success"] is False
    assert "全部缺失" in result["message"]


def test_clinical_agent_boolean_and_float_labels_normalized(temp_dir):
    df = pd.DataFrame({
        "PatientID": ["P001", "P002", "P003"],
        "Age": [50, 60, 70],
        "Label": [True, False, 1.0],
    })
    # Use Excel so boolean/float types survive round-trip.
    path = temp_dir / "data.xlsx"
    df.to_excel(path, index=False)

    agent = ClinicalAgent(llm_client=_make_mock_llm({
        "id_col": "PatientID",
        "label_col": "Label",
        "feature_cols": ["Age"],
    }))
    result = agent.run(str(path))
    assert result["success"] is True
    assert list(result["df"]["Label"]) == [1, 0, 1]


def test_clinical_agent_duplicate_patient_ids(temp_dir):
    df = pd.DataFrame({
        "PatientID": ["P001", "P001"],
        "Age": [50, 60],
        "Label": [0, 1],
    })
    path = temp_dir / "data.csv"
    df.to_csv(path, index=False)

    agent = ClinicalAgent(llm_client=_make_mock_llm({
        "id_col": "PatientID",
        "label_col": "Label",
        "feature_cols": ["Age"],
    }))
    result = agent.run(str(path))
    assert result["success"] is False
    assert "存在重复值" in result["message"]


def test_clinical_agent_excel_file(temp_dir):
    df = pd.DataFrame({
        "PatientID": ["P001", "P002"],
        "Age": [50, 60],
        "Sex": ["F", "M"],
        "Label": [0, 1],
    })
    path = temp_dir / "data.xlsx"
    df.to_excel(path, index=False)

    agent = ClinicalAgent(llm_client=_make_mock_llm({
        "id_col": "PatientID",
        "label_col": "Label",
        "feature_cols": ["Age", "Sex"],
    }))
    result = agent.run(str(path))
    assert result["success"] is True
    assert result["id_col"] == "PatientID"
    assert result["feature_cols"] == ["Age", "Sex"]
