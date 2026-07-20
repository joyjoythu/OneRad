import os

import pandas as pd
import pytest

from app.utils import parse_covariates


def test_parse_covariates_empty_string():
    assert parse_covariates("") == []


def test_parse_covariates_none():
    assert parse_covariates(None) == []


def test_parse_covariates_single_value():
    assert parse_covariates("Age") == ["Age"]


def test_parse_covariates_multiple_values_with_extra_spaces():
    assert parse_covariates("Age, Sex, BMI") == ["Age", "Sex", "BMI"]


def test_parse_covariates_trailing_comma():
    assert parse_covariates("Age, Sex,") == ["Age", "Sex"]


def test_parse_covariates_leading_and_trailing_spaces():
    assert parse_covariates("  Age  ,  Sex  ") == ["Age", "Sex"]


def test_parse_float_tuple_valid():
    from app.utils import parse_float_tuple
    assert parse_float_tuple("0.5,0.5,0.5") == (0.5, 0.5, 0.5)
    assert parse_float_tuple("  1 , 2 , 3  ") == (1.0, 2.0, 3.0)


def test_parse_float_tuple_empty():
    from app.utils import parse_float_tuple
    assert parse_float_tuple(None) is None
    assert parse_float_tuple("") is None
    assert parse_float_tuple("   ") is None


def test_parse_float_tuple_wrong_length():
    from app.utils import parse_float_tuple
    with pytest.raises(ValueError, match="需要 3 个数值"):
        parse_float_tuple("0.5,0.5")
    with pytest.raises(ValueError, match="需要 3 个数值"):
        parse_float_tuple("0.5,0.5,0.5,0.5")


def test_parse_float_tuple_invalid_value():
    from app.utils import parse_float_tuple
    with pytest.raises(ValueError):
        parse_float_tuple("0.5,abc,0.5")


# ---------------------------------------------------------------------------
# Pre-extracted feature / clinical helpers
# ---------------------------------------------------------------------------


def test_load_feature_csv_with_patient_id_column(tmp_path):
    from app.utils import _load_feature_csv
    df = pd.DataFrame({
        "patient_id": ["P001", "P002"],
        "original_mean": [1.0, 2.0],
    })
    path = tmp_path / "features.csv"
    df.to_csv(path, index=False)
    loaded = _load_feature_csv(str(path))
    assert list(loaded.columns) == ["patient_id", "original_mean"]
    assert loaded["patient_id"].tolist() == ["P001", "P002"]


def test_load_feature_csv_with_patient_id_index(tmp_path):
    from app.utils import _load_feature_csv
    df = pd.DataFrame({
        "original_mean": [1.0, 2.0],
    }, index=pd.Index(["P001", "P002"], name="patient_id"))
    path = tmp_path / "features.csv"
    df.to_csv(path)
    loaded = _load_feature_csv(str(path))
    assert "patient_id" in loaded.columns
    assert loaded["patient_id"].tolist() == ["P001", "P002"]


def test_load_feature_csv_falls_back_to_first_unique_column(tmp_path):
    from app.utils import _load_feature_csv
    df = pd.DataFrame({
        "ID": ["P001", "P002"],
        "original_mean": [1.0, 2.0],
    })
    path = tmp_path / "features.csv"
    df.to_csv(path, index=False)
    loaded = _load_feature_csv(str(path))
    assert "patient_id" in loaded.columns
    assert loaded["patient_id"].tolist() == ["P001", "P002"]


def test_load_feature_csv_missing_id_raises(tmp_path):
    from app.utils import _load_feature_csv
    df = pd.DataFrame({
        "original_mean": [1.0, 2.0],
        "original_std": [0.1, 0.2],
    })
    path = tmp_path / "features.csv"
    df.to_csv(path, index=False)
    with pytest.raises(ValueError, match="patient_id"):
        _load_feature_csv(str(path))


def test_load_clinical_for_analysis_auto_label(tmp_path):
    from app.utils import _load_clinical_for_analysis
    df = pd.DataFrame({
        "patient_id": ["P001", "P002", "P003"],
        "Age": [60, 70, 55],
        "Label": [0, 1, 0],
    })
    path = tmp_path / "clinical.csv"
    df.to_csv(path, index=False)
    loaded, id_col, label_col = _load_clinical_for_analysis(str(path))
    assert id_col == "patient_id"
    assert label_col == "Label"
    assert list(loaded["Label"]) == [0, 1, 0]


def test_load_clinical_for_analysis_explicit_label(tmp_path):
    from app.utils import _load_clinical_for_analysis
    df = pd.DataFrame({
        "ID": ["P001", "P002"],
        "Outcome": [0, 1],
    })
    path = tmp_path / "clinical.csv"
    df.to_csv(path, index=False)
    loaded, id_col, label_col = _load_clinical_for_analysis(str(path), label_col="Outcome")
    assert id_col == "patient_id"
    assert label_col == "Outcome"


def test_merge_feature_clinical_inner_join():
    from app.utils import _merge_feature_clinical
    feature_df = pd.DataFrame({
        "patient_id": ["P001", "P002", "P003"],
        "feat1": [1.0, 2.0, 3.0],
    })
    clinical_df = pd.DataFrame({
        "patient_id": ["P001", "P002"],
        "Label": [0, 1],
    })
    merged = _merge_feature_clinical(feature_df, clinical_df)
    assert len(merged) == 2
    assert set(merged["patient_id"]) == {"P001", "P002"}


def test_merge_feature_clinical_no_common_ids_raises():
    from app.utils import _merge_feature_clinical
    feature_df = pd.DataFrame({
        "patient_id": ["P001", "P002"],
        "feat1": [1.0, 2.0],
    })
    clinical_df = pd.DataFrame({
        "patient_id": ["P003", "P004"],
        "Label": [0, 1],
    })
    with pytest.raises(ValueError, match="无共同患者"):
        _merge_feature_clinical(feature_df, clinical_df)


def test_infer_covariates_filters_invalid_columns():
    from app.utils import _infer_covariates
    clinical_df = pd.DataFrame({
        "patient_id": ["P001"],
        "Label": [0],
        "Age": [60],
        "Sex": [1],
    })
    assert _infer_covariates(clinical_df, "patient_id", "Label", ["Age", "Sex", "BMI"]) == ["Age", "Sex"]


def test_infer_covariates_empty_explicit_returns_empty():
    from app.utils import _infer_covariates
    clinical_df = pd.DataFrame({
        "patient_id": ["P001"],
        "Label": [0],
    })
    assert _infer_covariates(clinical_df, "patient_id", "Label", []) == []


def test_resolve_id_matches_exact():
    """归一化后完全相等的 ID 直接匹配（含 "1.0" -> "1" 归并）。"""
    from app.utils import resolve_id_matches

    res = resolve_id_matches(["1000130", "1.0"], ["1000130", 1, "other"])
    assert res["mapping"] == {"1000130": "1000130", "1.0": "1"}
    assert res["ambiguous"] == []


def test_resolve_id_matches_compound_clinical_id_by_unique_part():
    """临床复合 ID（住院号_拼音）按唯一命中的部分匹配到特征 ID。"""
    from app.utils import resolve_id_matches

    res = resolve_id_matches(
        ["1008605_chenxiuzhen", "1028129_yyh"],
        ["chenxiuzhen", "1028129", "other"],
    )
    assert res["mapping"] == {
        "1008605_chenxiuzhen": "chenxiuzhen",
        "1028129_yyh": "1028129",
    }
    assert res["ambiguous"] == []


def test_resolve_id_matches_simple_clinical_id_against_compound_feature():
    """反向：临床纯拼音 ID 匹配到特征侧复合 ID 的唯一部分。"""
    from app.utils import resolve_id_matches

    res = resolve_id_matches(["chenliujuan"], ["905692_chenliujuan"])
    assert res["mapping"] == {"chenliujuan": "905692_chenliujuan"}
    assert res["ambiguous"] == []


def test_resolve_id_matches_ambiguous_when_multiple_parts_hit():
    """复合 ID 的多个部分分别命中不同特征 ID 时无法判定，列为歧义。"""
    from app.utils import resolve_id_matches

    res = resolve_id_matches(["1061852_lhy"], ["1061852", "lhy"])
    assert res["mapping"] == {}
    assert res["ambiguous"] == ["1061852_lhy"]


def test_resolve_id_matches_ambiguous_when_feature_claimed_twice():
    """同一个特征 ID 被多个临床 ID 部分匹配认领时，全部列为歧义。"""
    from app.utils import resolve_id_matches

    res = resolve_id_matches(
        ["1042296_yyy", "1042296_yyy22"], ["1042296"]
    )
    assert res["mapping"] == {}
    assert res["ambiguous"] == ["1042296_yyy", "1042296_yyy22"]


def test_resolve_id_matches_exact_wins_over_part_candidate():
    """特征 ID 已被精确匹配占用后，不再作为其他复合 ID 的部分候选。"""
    from app.utils import resolve_id_matches

    res = resolve_id_matches(["1042296", "1042296_yyy"], ["1042296"])
    assert res["mapping"] == {"1042296": "1042296"}
    # 1042296_yyy 的唯一候选已被占用 → 不匹配，但也不是"多候选歧义"
    assert res["ambiguous"] == []


def test_resolve_id_matches_no_candidate_is_unmatched_not_ambiguous():
    """完全无候选的临床 ID 不算歧义（临床表可含无影像患者）。"""
    from app.utils import resolve_id_matches

    res = resolve_id_matches(["nobody"], ["1000130"])
    assert res["mapping"] == {}
    assert res["ambiguous"] == []
