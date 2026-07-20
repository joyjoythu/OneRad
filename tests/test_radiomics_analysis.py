import numpy as np
import pandas as pd
import pytest

from app.radiomics_analysis import (
    _render_markdown_report,
    inspect_analysis_inputs,
    run_radiomics_cv_analysis,
)


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


def test_inspect_part_matches_compound_clinical_ids(tmp_path):
    """临床复合 ID（住院号_拼音）按唯一部分匹配计入 n_matched；
    多候选或多认领的歧义 ID 被排除并列入 ambiguous_ids。"""
    rng = np.random.RandomState(42)
    feat_ids = ["1000130", "chenxiuzhen", "1061852", "lhy", "1042296"]
    label = np.array([0, 1, 0, 1, 1])
    feat_df = pd.DataFrame({"patient_id": feat_ids})
    for j in range(4):
        feat_df[f"original_sig_{j}"] = rng.randn(5) + label * 1.5
    feat = tmp_path / "features.csv"
    feat_df.to_csv(feat, index=False)
    clin_ids = [
        "1000130",              # 精确匹配
        "1008605_chenxiuzhen",  # 唯一部分命中 chenxiuzhen
        "1061852_lhy",          # 两个部分均命中 → 歧义
        "1042296_yyy",          # 与下一行同时认领 1042296 → 歧义
        "1042296_yyy22",
    ]
    clin = tmp_path / "clinical.csv"
    pd.DataFrame({"patient_id": clin_ids, "Label": label}).to_csv(clin, index=False)

    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))

    assert result["status"] == "ready"
    assert result["resolved"]["n_matched"] == 2
    assert set(result["resolved"]["ambiguous_ids"]) == {
        "1061852_lhy", "1042296_yyy", "1042296_yyy22"}


def test_run_analysis_applies_part_match_mapping(tmp_path):
    """run 阶段同样应用部分匹配：复合临床 ID 的样本应进入合并后的分析。"""
    ids = [f"P{i:03d}" for i in range(60)]
    feat = tmp_path / "features.csv"
    label = _write_feature_csv(feat, ids)
    clin = tmp_path / "clinical.csv"
    compound_ids = [f"{1000000 + i}_P{i:03d}" for i in range(60)]
    _write_clinical_csv(clin, compound_ids, label)

    out_dir = str(tmp_path / "analysis_out")
    result = run_radiomics_cv_analysis(
        feature_csv=str(feat), clinical=str(clin), output_dir=out_dir,
        id_col="patient_id", label_col="Label")

    assert result["success"] is True
    assert result["n_matched"] == 60
    case_df = pd.read_csv(result["outputs"]["case_predictions"])
    assert len(case_df) == 60
    # 合并以特征侧 patient_id 为准
    assert set(case_df["patient_id"]) == set(ids)


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
    assert "折交叉验证逐折指标" in md
    assert "均值±标准差" in md
    assert "PPV" in md and "NPV" in md and "F1" in md
    assert result["n_matched"] == 60


def test_render_markdown_report_formats(tmp_path):
    """Markdown 报告:p<0.001 归并显示，数值 3 位小数，含逐折表。"""
    analysis_result = {
        "success": True,
        "n_samples": 60,
        "selected_features": ["original_sig_0"],
        "model_results": {
            "coefficients": {"original_sig_0": 0.12345},
            "odds_ratios": {"original_sig_0": 1.13141},
            "ci_lower": {"original_sig_0": 1.01},
            "ci_upper": {"original_sig_0": 1.26},
            "p_values": {"original_sig_0": 0.0004},
        },
        "metrics": {
            "auc": 0.8567, "auc_ci": [0.75, 0.94],
            "accuracy": 0.8, "sensitivity": 0.82, "specificity": 0.78,
            "ppv": 0.81, "npv": 0.79, "f1": 0.815,
            "threshold": 0.5, "confusion_matrix": [[24, 6], [6, 24]],
        },
        "cv_metrics": {
            "folds": [
                {"fold": i + 1, "auc": 0.8, "accuracy": 0.8, "sensitivity": 0.8,
                 "specificity": 0.8, "ppv": 0.8, "npv": 0.8, "f1": 0.8,
                 "threshold": 0.5}
                for i in range(5)
            ],
            "mean": {"auc": 0.8, "accuracy": 0.8, "sensitivity": 0.8,
                     "specificity": 0.8, "ppv": 0.8, "npv": 0.8, "f1": 0.8,
                     "threshold": 0.5},
            "std": {"auc": 0.02, "accuracy": 0.02, "sensitivity": 0.02,
                    "specificity": 0.02, "ppv": 0.02, "npv": 0.02, "f1": 0.02,
                    "threshold": 0.01},
        },
    }
    path = _render_markdown_report(
        analysis_result, outputs={}, n_matched=60, covariates=[],
        output_dir=str(tmp_path), n_splits=5)
    md = open(path, encoding="utf-8").read()
    assert "<0.001" in md
    assert "0.0004" not in md
    assert "| 0.123 |" in md  # 系数 3 位小数
    assert "5 折交叉验证逐折指标" in md
    assert "0.800±0.020" in md


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


def test_run_analysis_fails_without_id_col(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        label_col="Label")
    assert result["success"] is False
    assert "id_col" in result["message"]


def test_run_analysis_fails_with_empty_id_col(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="", label_col="Label")
    assert result["success"] is False
    assert "id_col" in result["message"]


def test_run_analysis_fails_on_nan_label(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    clin_df = pd.read_csv(clin)
    clin_df.loc[0, "Label"] = float("nan")
    clin_df.to_csv(clin, index=False)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label")
    assert result["success"] is False
    assert "缺失" in result["message"]


def test_run_analysis_fails_on_single_class_label(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    clin_df = pd.read_csv(clin)
    clin_df["Label"] = 1
    clin_df.to_csv(clin, index=False)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label")
    assert result["success"] is False
    assert "同时包含 0 和 1" in result["message"]


def test_run_analysis_curve_failure_does_not_abort(tmp_path, monkeypatch):
    feat, clin = _make_run_inputs(tmp_path)

    def _raise(*args, **kwargs):
        raise RuntimeError("plot intentionally failed")

    monkeypatch.setattr("app.radiomics_analysis.plot_roc_curve", _raise)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label")
    assert result["success"] is True
    assert result["outputs"]["roc_curve"] is None
    assert result["outputs"]["calibration_curve"]
    assert result["outputs"]["report_docx"]
