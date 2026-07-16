import numpy as np
import pandas as pd
import pytest

from app.radiomics_analysis import inspect_analysis_inputs


def _write_feature_csv(path, ids, n=8, seed=42):
    rng = np.random.RandomState(seed)
    df = pd.DataFrame({"patient_id": ids})
    label = np.array([i % 2 for i in range(len(ids))])
    for j in range(6):
        df[f"original_sig_{j}"] = rng.randn(len(ids)) + label * 1.5
    for j in range(2):
        df[f"wavelet-HHH_noise_{j}"] = rng.randn(len(ids))
    df.to_csv(path, index=False)
    return label


def _write_clinical_csv(path, ids, label, label_name="Label", extra_binary=False):
    rng = np.random.RandomState(1)
    df = pd.DataFrame({"patient_id": ids, label_name: label,
                       "age": rng.randint(30, 80, len(ids))})
    if extra_binary:
        df["group2"] = rng.randint(0, 2, len(ids))
    df.to_csv(path, index=False)


IDS = [f"P{i:03d}" for i in range(60)]


def test_inspect_ready_with_explicit_paths(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "ready"
    resolved = result["resolved"]
    assert resolved["id_col"] == "patient_id"
    assert resolved["label_col"] == "Label"
    assert resolved["n_matched"] == 60
    assert resolved["n_features"] == 8
    assert resolved["output_dir"] == str(tmp_path / "radiomics_analysis")


def test_inspect_auto_discovers_clinical(tmp_path):
    feat_dir = tmp_path / "radiomics_features"
    feat_dir.mkdir()
    label = _write_feature_csv(feat_dir / "radiomics_features.csv", IDS)
    _write_clinical_csv(tmp_path / "clinical.csv", IDS, label)
    result = inspect_analysis_inputs(str(tmp_path))
    assert result["status"] == "ready"
    assert result["resolved"]["clinical"] == str(tmp_path / "clinical.csv")


def test_inspect_missing_feature_csv_returns_error(tmp_path):
    result = inspect_analysis_inputs(str(tmp_path))
    assert result["status"] == "error"
    assert "特征" in result["message"]


def test_inspect_multiple_clinical_candidates_asks(tmp_path):
    feat = tmp_path / "features.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(tmp_path / "a.csv", IDS, label)
    _write_clinical_csv(tmp_path / "b.csv", IDS, label)
    result = inspect_analysis_inputs(str(tmp_path), feature_csv=str(feat))
    assert result["status"] == "need_clarification"
    assert result["questions"][0]["field"] == "clinical"
    assert len(result["questions"][0]["candidates"]) == 2


def test_inspect_multiple_binary_columns_asks_label(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label, extra_binary=True)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "need_clarification"
    fields = [q["field"] for q in result["questions"]]
    assert "label_col" in fields


def test_inspect_no_id_match_asks_id(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, [f"X{i:03d}" for i in range(60)], label)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "need_clarification"
    fields = [q["field"] for q in result["questions"]]
    assert "id_col" in fields


def test_inspect_invalid_explicit_label_returns_error(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin),
        label_col="age")
    assert result["status"] == "error"
    assert "0/1" in result["message"]


def test_inspect_explicit_label_and_covariates(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label, label_name="group")
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin),
        label_col="group", covariates=["age", "not_a_column"])
    assert result["status"] == "ready"
    assert result["resolved"]["label_col"] == "group"
    assert result["resolved"]["covariates"] == ["age"]
