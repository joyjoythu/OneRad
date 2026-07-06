import pandas as pd
import pytest

from app.clinical import run_matching


def test_run_matching_basic():
    pairs = [
        {"patient_id": "P001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
        {"patient_id": "P002", "image_path": "b.nii", "mask_path": "b_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001", "P002", "P003"],
        "Age": [50, 60, 70],
        "Label": [0, 1, 0],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result["success"] is True
    assert result["match_stats"]["matched"] == 2
    assert "P003" in result["unmatched_clinical_ids"]


def test_run_matching_case_insensitive():
    pairs = [
        {"patient_id": "p001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result["success"] is True
    assert result["match_stats"]["matched"] == 1
    assert result["matched_ids"] == ["p001"]


def test_run_matching_strips_file_extension():
    pairs = [
        {"patient_id": "P001.nii.gz", "image_path": "a.nii.gz", "mask_path": "a_mask.nii.gz"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result["success"] is True
    assert result["match_stats"]["matched"] == 1
    assert result["matched_ids"] == ["P001.nii.gz"]


def test_run_matching_fuzzy():
    pairs = [
        {"patient_id": "P-001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    result = run_matching(pairs, df, id_col="PatientID", fuzzy_threshold=0.8)
    assert result["success"] is True
    assert result["match_stats"]["matched"] == 1
    assert result["match_method"] == "fuzzy"
    assert result["fuzzy_map"] == {"p-001": "p001"}


def test_run_matching_empty_discovery_pairs():
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    result = run_matching([], df, id_col="PatientID")
    assert result["success"] is False
    assert "Discovery pairs 为空" in result["message"]


def test_run_matching_empty_clinical_df():
    pairs = [
        {"patient_id": "P001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
    ]
    result = run_matching(pairs, pd.DataFrame(), id_col="PatientID")
    assert result["success"] is False
    assert "临床表格为空" in result["message"]


def test_run_matching_missing_id_col():
    pairs = [
        {"patient_id": "P001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001"],
        "Age": [50],
        "Label": [0],
    })
    result = run_matching(pairs, df, id_col="MissingID")
    assert result["success"] is False
    assert "ID 列 'MissingID' 不存在" in result["message"]


def test_run_matching_no_matching_ids():
    pairs = [
        {"patient_id": "P001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P999"],
        "Age": [50],
        "Label": [0],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result["success"] is False
    assert "无任何 ID 匹配成功" in result["message"]


def test_run_matching_duplicate_normalized_clinical_ids():
    pairs = [
        {"patient_id": "P001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001", "p001"],
        "Age": [50, 60],
        "Label": [0, 1],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result["success"] is False
    assert "临床 ID 列归一化后存在重复" in result["message"]
    assert "p001" in result["message"]
