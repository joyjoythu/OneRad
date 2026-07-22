import glob
import json
import logging
import os

import numpy as np
import pandas as pd
import pytest

from app.clinical import translate_column_names
from app.radiomics_analysis import (
    _render_markdown_report,
    _resolve_translation_conflicts,
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


def test_inspect_hyperparams_defaults_and_passthrough(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label)
    # 默认值
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    resolved = result["resolved"]
    assert resolved["n_splits"] == 5
    assert resolved["max_lasso_features"] == 100
    assert resolved["random_state"] == 42
    # 自定义透传
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin),
        n_splits=3, max_lasso_features=20, random_state=7)
    resolved = result["resolved"]
    assert resolved["n_splits"] == 3
    assert resolved["max_lasso_features"] == 20
    assert resolved["random_state"] == 7


def test_inspect_hyperparams_invalid(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label)
    for kwargs in ({"n_splits": 1},
                   {"max_lasso_features": 0},
                   {"random_state": -1}):
        result = inspect_analysis_inputs(
            str(tmp_path), feature_csv=str(feat), clinical=str(clin), **kwargs)
        assert result["status"] == "error", kwargs


def test_run_analysis_writes_reproduction_files(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    out_dir = str(tmp_path / "analysis_out")
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin, output_dir=out_dir,
        id_col="patient_id", label_col="Label",
        max_lasso_features=50, random_state=7,
        project_path=str(tmp_path))
    assert result["success"] is True
    outputs = result["outputs"]
    params_path = outputs["params_snapshot"]
    script_path = outputs["reproduction_script"]
    assert os.path.exists(params_path)
    assert os.path.exists(script_path)
    assert os.path.dirname(params_path) == out_dir
    assert os.path.dirname(script_path) == out_dir

    params = json.loads(open(params_path, encoding="utf-8").read())
    # 路径一律相对项目根，项目整体搬迁后仍可复跑
    assert params["feature_csv"] == "features.csv"
    assert params["clinical"] == "clinical.csv"
    assert params["output_dir"] == "analysis_out"
    assert params["project_root"] == ".."
    assert params["id_col"] == "patient_id"
    assert params["label_col"] == "Label"
    assert params["n_splits"] == 5
    assert params["max_lasso_features"] == 50
    assert params["random_state"] == 7

    script = open(script_path, encoding="utf-8").read()
    assert "analysis_params.json" in script
    assert "run_radiomics_cv_analysis" in script
    assert "project_root" in script


# ---------------------------------------------------------------------------
# 中文临床列名自动翻译
# ---------------------------------------------------------------------------

class _FakeLLMClient:
    """模拟 LLMClient：call_json 返回预设翻译映射；call 原样返回（方法学润色）。"""

    def __init__(self, mapping=None, fail=False):
        self._mapping = mapping or {}
        self._fail = fail

    def call_json(self, system, user, **kwargs):
        if self._fail:
            raise RuntimeError("LLM unavailable")
        return dict(self._mapping)

    def call(self, system, user, **kwargs):
        return user


def _make_chinese_clinical_inputs(tmp_path, n=60, seed=42, label_name="Label"):
    ids = [f"P{i:03d}" for i in range(n)]
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, ids, seed=seed)
    rng = np.random.RandomState(1)
    pd.DataFrame({"patient_id": ids, label_name: label,
                  "年龄": rng.randint(30, 80, n)}).to_csv(clin, index=False)
    return str(feat), str(clin)


def test_translate_column_names_filters_invalid():
    """非法译名（非 ASCII / 空 / 缺失）被过滤，原名保持不译。"""
    llm = _FakeLLMClient({"年龄": "Age", "性别": "性Gender", "吸烟史": " "})
    mapping = translate_column_names(["年龄", "性别", "吸烟史", " BMI "], llm)
    assert mapping == {"年龄": "Age"}
    # 无 llm_client 或空列表直接返回 {}
    assert translate_column_names(["年龄"], None) == {}
    assert translate_column_names([], llm) == {}


def test_translate_column_names_raises_on_bad_response():
    llm = _FakeLLMClient()
    llm.call_json = lambda *a, **k: None
    with pytest.raises(ValueError):
        translate_column_names(["年龄"], llm)


def test_resolve_translation_conflicts():
    """译名与既有列名或彼此冲突时追加 _2、_3 后缀。"""
    resolved = _resolve_translation_conflicts(
        {"年龄": "Age", "岁数": "Age"}, taken={"Age"})
    assert resolved == {"年龄": "Age_2", "岁数": "Age_3"}


def test_run_analysis_translates_chinese_column_names(tmp_path):
    """mock LLM 翻译后跑完整分析：产物全部为英文名，映射与复现文件齐备。"""
    feat, clin = _make_chinese_clinical_inputs(tmp_path)
    out_dir = str(tmp_path / "analysis_out")
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin, output_dir=out_dir,
        id_col="patient_id", label_col="Label", covariates=["年龄"],
        project_path=str(tmp_path),
        llm_client=_FakeLLMClient({"年龄": "Age"}))
    assert result["success"] is True
    outputs = result["outputs"]

    # 映射 CSV 落盘
    map_df = pd.read_csv(outputs["covariate_name_mapping"])
    assert list(map_df.columns) == ["original_name", "english_name"]
    assert dict(zip(map_df["original_name"],
                    map_df["english_name"])) == {"年龄": "Age"}

    # 产物中不再出现中文特征名，英文协变量进入模型
    coefs = result["analysis_result"]["model_results"]["coefficients"]
    assert "Age" in coefs
    assert all(str(k).isascii() for k in coefs)
    feat_df = pd.read_csv(outputs["selected_features"])
    assert all(str(v).isascii() for v in feat_df["feature"])
    analysis_json = json.loads(
        open(outputs["analysis_result_json"], encoding="utf-8").read())
    assert all(str(k).isascii()
               for k in analysis_json["model_results"]["coefficients"])
    for shap_csv in glob.glob(os.path.join(out_dir, "shap", "shap_values_fold*.csv")):
        cols = pd.read_csv(shap_csv, nrows=0).columns
        assert all(str(c).isascii() for c in cols), shap_csv

    # report.md 与 docx 方法小节以 "Age（年龄）" 对照呈现
    md = open(outputs["report_md"], encoding="utf-8").read()
    assert "临床协变量：Age（年龄）" in md
    from docx import Document
    doc = Document(outputs["report_docx"])
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Age（年龄）" in text

    # analysis_params.json 含 column_name_mapping，协变量已英文化
    params = json.loads(
        open(outputs["params_snapshot"], encoding="utf-8").read())
    assert params["column_name_mapping"] == {"年龄": "Age"}
    assert params["covariates"] == ["Age"]

    # 复现脚本应用映射（查表重命名，不调 LLM）
    script = open(outputs["reproduction_script"], encoding="utf-8").read()
    assert "column_name_mapping" in script


def test_run_analysis_translates_chinese_label_column(tmp_path):
    """中文标签列名也一并翻译，保持数据一致。"""
    feat, clin = _make_chinese_clinical_inputs(tmp_path, label_name="结局")
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="结局",
        llm_client=_FakeLLMClient({"结局": "Outcome", "年龄": "Age"}))
    assert result["success"] is True
    params = json.loads(open(
        result["outputs"]["params_snapshot"], encoding="utf-8").read())
    assert params["column_name_mapping"] == {"结局": "Outcome", "年龄": "Age"}


def test_run_analysis_applies_column_name_mapping_without_llm(tmp_path):
    """复跑路径：按快照映射直接重命名，不调 LLM 也不重写映射 CSV。"""
    feat, clin = _make_chinese_clinical_inputs(tmp_path)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label", covariates=["Age"],
        column_name_mapping={"年龄": "Age"})
    assert result["success"] is True
    coefs = result["analysis_result"]["model_results"]["coefficients"]
    assert "Age" in coefs
    assert "covariate_name_mapping" not in result["outputs"]
    params = json.loads(open(
        result["outputs"]["params_snapshot"], encoding="utf-8").read())
    assert params["column_name_mapping"] == {}


def test_run_analysis_chinese_columns_without_llm_keeps_original(tmp_path, caplog):
    """无 llm_client：记 warning 保持原名，不写映射文件。"""
    feat, clin = _make_chinese_clinical_inputs(tmp_path)
    with caplog.at_level(logging.WARNING, logger="app.radiomics_analysis"):
        result = run_radiomics_cv_analysis(
            feature_csv=feat, clinical=clin,
            output_dir=str(tmp_path / "out"),
            id_col="patient_id", label_col="Label", covariates=["年龄"])
    assert result["success"] is True
    assert any("非 ASCII" in r.message for r in caplog.records)
    assert "covariate_name_mapping" not in result["outputs"]
    coefs = result["analysis_result"]["model_results"]["coefficients"]
    assert "年龄" in coefs
    params = json.loads(open(
        result["outputs"]["params_snapshot"], encoding="utf-8").read())
    assert params["column_name_mapping"] == {}
    assert params["covariates"] == ["年龄"]


def test_run_analysis_translation_failure_keeps_original(tmp_path, caplog):
    """翻译调用失败：记 warning 保持原名，分析照常完成。"""
    feat, clin = _make_chinese_clinical_inputs(tmp_path)
    with caplog.at_level(logging.WARNING, logger="app.radiomics_analysis"):
        result = run_radiomics_cv_analysis(
            feature_csv=feat, clinical=clin,
            output_dir=str(tmp_path / "out"),
            id_col="patient_id", label_col="Label", covariates=["年龄"],
            llm_client=_FakeLLMClient(fail=True))
    assert result["success"] is True
    assert any("翻译失败" in r.message for r in caplog.records)
    assert "covariate_name_mapping" not in result["outputs"]
    assert "年龄" in result["analysis_result"]["model_results"]["coefficients"]
