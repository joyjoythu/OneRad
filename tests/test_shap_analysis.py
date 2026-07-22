"""逐折 SHAP 可解释性 + 逐折产物落盘的测试（见 shap-interpretability 设计文档）。"""

import os

import numpy as np
import pandas as pd
import pytest

from app.radiomics_analysis import run_radiomics_cv_analysis


def _write_feature_csv(path, ids, seed=42):
    rng = np.random.RandomState(seed)
    df = pd.DataFrame({"patient_id": ids})
    label = np.array([i % 2 for i in range(len(ids))])
    for j in range(6):
        df[f"original_sig_{j}"] = rng.randn(len(ids)) + label * 1.5
    for j in range(2):
        df[f"wavelet-HHH_noise_{j}"] = rng.randn(len(ids))
    df.to_csv(path, index=False)
    return label


def _write_clinical_csv(path, ids, label):
    rng = np.random.RandomState(1)
    pd.DataFrame({"patient_id": ids, "Label": label,
                  "age": rng.randint(30, 80, len(ids))}).to_csv(path, index=False)


def _make_run_inputs(tmp_path, n=60):
    ids = [f"P{i:03d}" for i in range(n)]
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, ids)
    _write_clinical_csv(clin, ids, label)
    return str(feat), str(clin), ids


def _run(tmp_path, **kwargs):
    feat, clin, ids = _make_run_inputs(tmp_path)
    out_dir = str(tmp_path / "analysis_out")
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin, output_dir=out_dir,
        id_col="patient_id", label_col="Label", **kwargs)
    assert result["success"] is True, result["message"]
    return result, out_dir, ids


def test_full_run_produces_all_per_fold_artifacts(tmp_path):
    """完整流程：shap/、curves/、predictions/、lasso/ 每折产物齐全。"""
    result, out_dir, _ = _run(tmp_path)
    for fold in range(1, 6):
        for rel in (
            os.path.join("lasso", f"lasso_path_fold{fold}.png"),
            os.path.join("shap", f"shap_summary_fold{fold}.png"),
            os.path.join("shap", f"shap_bar_fold{fold}.png"),
            os.path.join("shap", f"shap_values_fold{fold}.csv"),
            os.path.join("predictions", f"case_predictions_fold{fold}.csv"),
            os.path.join("curves", "roc", f"roc_fold{fold}.png"),
            os.path.join("curves", "calibration", f"calibration_fold{fold}.png"),
            os.path.join("curves", "dca", f"dca_fold{fold}.png"),
        ):
            assert os.path.exists(os.path.join(out_dir, rel)), f"missing {rel}"
        # lasso 图不再落在输出根目录
        assert not os.path.exists(os.path.join(out_dir, f"lasso_path_fold{fold}.png"))

        pred_df = pd.read_csv(
            os.path.join(out_dir, "predictions", f"case_predictions_fold{fold}.csv"))
        assert list(pred_df.columns) == ["patient_id", "y_true", "prob", "y_pred"]
        assert len(pred_df) == 12  # 60 例 / 5 折


def test_shap_values_csv_columns(tmp_path):
    """shap_values CSV：含 patient_id 列，特征列 = 当折模型输入（含临床协变量）。"""
    result, out_dir, ids = _run(tmp_path, covariates=["age"])
    all_features = {f"original_sig_{j}" for j in range(6)} | {
        f"wavelet-HHH_noise_{j}" for j in range(2)} | {"age"}
    for fold in range(1, 6):
        df = pd.read_csv(
            os.path.join(out_dir, "shap", f"shap_values_fold{fold}.csv"))
        assert "patient_id" in df.columns
        feature_cols = [c for c in df.columns if c != "patient_id"]
        assert feature_cols, f"fold{fold} 无特征列"
        assert set(feature_cols) <= all_features
        # 临床协变量全部保留，必在当折模型输入中
        assert "age" in feature_cols
        assert len(df) == 48  # 60 例中当折训练集 48 例
        assert set(df["patient_id"]) <= set(ids)


def test_shap_csv_columns_match_model_inputs(tmp_path, monkeypatch):
    """CSV 特征列与传给 shap.summary_plot 的当折模型输入特征名完全一致。"""
    import shap
    real_summary_plot = shap.summary_plot
    captured = []

    def _spy(shap_values, features, feature_names=None, **kwargs):
        captured.append(list(feature_names))
        return real_summary_plot(shap_values, features,
                                 feature_names=feature_names, **kwargs)

    monkeypatch.setattr(shap, "summary_plot", _spy)
    result, out_dir, _ = _run(tmp_path, covariates=["age"])
    # 每折 beeswarm + bar 各一次，特征名相同
    assert len(captured) == 10
    for fold in range(1, 6):
        df = pd.read_csv(
            os.path.join(out_dir, "shap", f"shap_values_fold{fold}.csv"))
        csv_features = [c for c in df.columns if c != "patient_id"]
        assert csv_features == captured[2 * (fold - 1)]
        assert captured[2 * (fold - 1)] == captured[2 * (fold - 1) + 1]


def test_shap_failure_does_not_abort(tmp_path, monkeypatch):
    """mock shap 抛异常：流程不中断，其余产物正常，shap 产物缺失。"""
    import shap

    def _raise(*args, **kwargs):
        raise RuntimeError("shap intentionally failed")

    monkeypatch.setattr(shap, "LinearExplainer", _raise)
    monkeypatch.setattr(shap, "KernelExplainer", _raise)
    result, out_dir, _ = _run(tmp_path)
    assert result["success"] is True
    for fold in range(1, 6):
        assert os.path.exists(
            os.path.join(out_dir, "predictions", f"case_predictions_fold{fold}.csv"))
        assert os.path.exists(
            os.path.join(out_dir, "curves", "roc", f"roc_fold{fold}.png"))
        assert os.path.exists(
            os.path.join(out_dir, "lasso", f"lasso_path_fold{fold}.png"))
    assert not os.listdir(os.path.join(out_dir, "shap"))
    assert result["outputs"]["report_docx"]
    assert result["analysis_result"]["shap_plot_paths"] == []


def test_plot_paths_contain_all_shap_and_single_lasso(tmp_path):
    """plot_paths 含全部 10 张 SHAP 图；LASSO path 仅 fold1 一张。"""
    result, out_dir, _ = _run(tmp_path)
    plot_paths = result["analysis_result"]["plot_paths"]
    shap_in_plots = [p for p in plot_paths
                     if os.path.basename(p).startswith(
                         ("shap_summary_fold", "shap_bar_fold"))]
    lasso_in_plots = [p for p in plot_paths
                      if os.path.basename(p).startswith("lasso_path_fold")]
    assert len(shap_in_plots) == 10
    assert len(lasso_in_plots) == 1
    assert os.path.basename(lasso_in_plots[0]) == "lasso_path_fold1.png"
    # outputs 汇总完整集合
    assert len(result["outputs"]["shap_plots"]) == 10
    assert len(result["outputs"]["lasso_paths"]) == 5
    for p in shap_in_plots + lasso_in_plots:
        assert os.path.exists(p)

    # report.md 含 SHAP 小节与全部 SHAP 图链接
    md = open(result["outputs"]["report_md"], encoding="utf-8").read()
    assert "SHAP 可解释性" in md
    for fold in range(1, 6):
        assert f"shap/shap_summary_fold{fold}.png" in md
        assert f"shap/shap_bar_fold{fold}.png" in md
    # report.md 只展示 fold1 的 LASSO path
    assert "lasso/lasso_path_fold1.png" in md
    assert "lasso_path_fold2" not in md
