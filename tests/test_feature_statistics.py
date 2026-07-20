import numpy as np
import pandas as pd

from app.feature_statistics import inspect_statistics_inputs, run_feature_statistics


def _write_feature_csv(path, ids, seed=42):
    rng = np.random.RandomState(seed)
    df = pd.DataFrame({"patient_id": ids})
    for j in range(3):
        df[f"original_sig_{j}"] = rng.randn(len(ids))
    df.to_csv(path, index=False)


def _write_selected_csv(path, features):
    pd.DataFrame({"feature": features}).to_csv(path, index=False)


def test_inspect_part_matches_compound_clinical_ids(tmp_path):
    """临床复合 ID（住院号_拼音）按唯一部分匹配计入 n_matched；
    歧义 ID 被排除并列入 ambiguous_ids。"""
    feat_ids = ["1000130", "chenxiuzhen", "1061852", "lhy", "1042296"]
    clin_ids = [
        "1000130",              # 精确匹配
        "1008605_chenxiuzhen",  # 唯一部分命中 chenxiuzhen
        "1061852_lhy",          # 两个部分均命中 → 歧义
        "1042296_yyy",          # 与下一行同时认领 1042296 → 歧义
        "1042296_yyy22",
    ]
    feat = tmp_path / "features.csv"
    _write_feature_csv(feat, feat_ids)
    clin = tmp_path / "clinical.csv"
    pd.DataFrame({"ID": clin_ids, "Label": [0, 1, 0, 1, 1]}).to_csv(clin, index=False)
    sel = tmp_path / "selected.csv"
    _write_selected_csv(sel, ["original_sig_0"])

    result = inspect_statistics_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin),
        selected_features_csv=str(sel))

    assert result["status"] == "ready"
    assert result["resolved"]["n_matched"] == 2
    assert set(result["resolved"]["ambiguous_ids"]) == {
        "1061852_lhy", "1042296_yyy", "1042296_yyy22"}


def test_run_applies_part_match_mapping(tmp_path):
    """run 阶段应用部分匹配：复合临床 ID 的样本进入分组统计。"""
    feat_ids = ["1000130", "chenxiuzhen", "p3", "p4", "p5", "p6"]
    clin_ids = ["1000130", "1008605_chenxiuzhen", "p3", "p4", "p5", "p6"]
    feat = tmp_path / "features.csv"
    _write_feature_csv(feat, feat_ids)
    clin = tmp_path / "clinical.csv"
    pd.DataFrame({"ID": clin_ids, "Label": [0, 1, 0, 1, 0, 1]}).to_csv(
        clin, index=False)

    result = run_feature_statistics(
        feature_csv=str(feat), clinical=str(clin), id_col="ID",
        label_col="Label", selected_features=["original_sig_0"],
        output_dir=str(tmp_path / "stats_out"))

    assert result["success"] is True
    row = result["results"][0]
    assert row["group0_n"] == 3
    assert row["group1_n"] == 3
