import numpy as np
import pandas as pd
import pytest

from app.radiomics_analysis import inspect_analysis_inputs, run_radiomics_cv_analysis


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
    _write_clinical_csv(clin, IDS, label, label_name="group", extra_binary=True)
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


def test_inspect_prefers_label_named_column(tmp_path):
    """存在名为 Label 的 0/1 列时优先使用，即使有其他 0/1 列也不询问。"""
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label, extra_binary=True)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "ready"
    assert result["resolved"]["label_col"] == "Label"



def test_inspect_continuous_column_not_treated_as_binary(tmp_path):
    """[0,2) 区间的连续列不得被识别为 0/1 标签候选。"""
    feat = tmp_path / "features.csv"
    label = _write_feature_csv(feat, IDS)
    clin = tmp_path / "clinical.csv"
    rng = np.random.RandomState(3)
    df = pd.DataFrame({"patient_id": IDS, "Label": label,
                       "score": rng.uniform(0, 2, len(IDS))})
    df.to_csv(clin, index=False)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    # score 不应成为候选；Label 仍是唯一 0/1 列 → ready
    assert result["status"] == "ready"
    assert result["resolved"]["label_col"] == "Label"


def test_inspect_explicit_id_col_zero_match_returns_error(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin),
        id_col="age")
    assert result["status"] == "error"
    assert "无任何匹配" in result["message"]


def test_inspect_tie_id_columns_asks(tmp_path):
    """两列与特征 ID 匹配数相同时列出并列候选。"""
    feat = tmp_path / "features.csv"
    label = _write_feature_csv(feat, IDS)
    clin = tmp_path / "clinical.csv"
    df = pd.DataFrame({"patient_id": IDS, "pid_copy": IDS, "Label": label})
    df.to_csv(clin, index=False)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "need_clarification"
    q = [q for q in result["questions"] if q["field"] == "id_col"]
    assert q and set(q[0]["candidates"]) == {"patient_id", "pid_copy"}


def test_inspect_float_ids_normalized(tmp_path):
    """临床 ID 列被读成浮点（1.0）时仍能匹配特征的整型 ID（1）。"""
    rng = np.random.RandomState(42)
    ids = [str(i) for i in range(60)]
    label = np.array([i % 2 for i in range(60)])
    feat_df = pd.DataFrame({"patient_id": ids})
    for j in range(4):
        feat_df[f"original_sig_{j}"] = rng.randn(60) + label * 1.5
    feat = tmp_path / "features.csv"
    feat_df.to_csv(feat, index=False)
    clin = tmp_path / "clinical.csv"
    # 直接把 ID 写成 1.0/2.0 形式的浮点
    clin_df = pd.DataFrame({"patient_id": [float(i) for i in range(60)],
                            "Label": label})
    clin_df.to_csv(clin, index=False)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "ready"
    assert result["resolved"]["n_matched"] == 60


def _make_run_inputs(tmp_path, n=60, seed=42):
    ids = [f"P{i:03d}" for i in range(n)]
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, ids, seed=seed)
    _write_clinical_csv(clin, ids, label)
    return str(feat), str(clin)


def test_run_analysis_end_to_end(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    out_dir = str(tmp_path / "analysis_out")
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin, output_dir=out_dir,
        id_col="patient_id", label_col="Label")
    assert result["success"] is True
    outputs = result["outputs"]
    for key in ("case_predictions", "selected_features", "roc_curve",
                "calibration_curve", "dca_curve", "report_docx", "report_md"):
        assert outputs[key], f"missing output {key}"
        import os
        assert os.path.exists(outputs[key]), f"{key} not on disk"

    case_df = pd.read_csv(outputs["case_predictions"])
    assert list(case_df.columns) == ["patient_id", "y_true", "oof_prob", "y_pred"]
    assert len(case_df) == 60

    feat_df = pd.read_csv(outputs["selected_features"])
    assert list(feat_df.columns) == ["feature", "coefficient", "odds_ratio",
                                     "ci_lower", "ci_upper", "p_value"]
    assert len(feat_df) >= 1

    md = open(outputs["report_md"], encoding="utf-8").read()
    assert "AUC" in md
    assert result["n_matched"] == 60


def test_run_analysis_fails_when_class_too_small(tmp_path):
    ids = [f"P{i:03d}" for i in range(30)]
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    _write_feature_csv(feat, ids)
    # 阳性仅 2 例，小于 5 折
    df = pd.DataFrame({"patient_id": ids,
                       "Label": [1, 1] + [0] * 28})
    df.to_csv(clin, index=False)
    result = run_radiomics_cv_analysis(
        feature_csv=str(feat), clinical=str(clin),
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label")
    assert result["success"] is False
    assert "折数" in result["message"]


def test_run_analysis_cancelled_before_start(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label",
        should_cancel=lambda: True)
    assert result["success"] is False
    assert result["cancelled"] is True


def test_run_analysis_fails_without_label_col(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id")
    assert result["success"] is False
    assert "label_col" in result["message"]
