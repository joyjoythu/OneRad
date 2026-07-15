import pytest
from pathlib import Path
from app.radiomics_discovery import discover_pairs


def test_high_confidence_exact_match(tmp_path):
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1.nii.gz").write_text("mask")

    result = discover_pairs(str(tmp_path))
    assert result["success"] is True
    assert len(result["pairs"]["high"]) == 1
    assert result["pairs"]["high"][0]["patient_id"] == "case_001"
    assert result["pairs"]["high"][0]["sequence"] == "T1"


def test_medium_confidence_suffix(tmp_path):
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1_mask.nii.gz").write_text("mask")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["medium"]) == 1


def test_medium_confidence_token_intersection(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()
    (tmp_path / "images" / "sub-01_T1w.nii.gz").write_text("img")
    (tmp_path / "masks" / "sub-01_seg.nii.gz").write_text("mask")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["medium"]) == 1
    assert result["pairs"]["medium"][0]["patient_id"] == "sub-01"


def test_low_confidence_multiple_candidates(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()
    (tmp_path / "images" / "abc.nii.gz").write_text("img")
    (tmp_path / "masks" / "xyz_mask.nii.gz").write_text("mask1")
    (tmp_path / "masks" / "xyz_seg.nii.gz").write_text("mask2")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["low"]) == 1
    assert len(result["pairs"]["low"][0]["candidates"]) == 2


def test_missing_images_dir(tmp_path):
    result = discover_pairs(str(tmp_path))
    assert result["success"] is False
    assert "images" in result["message"].lower()
