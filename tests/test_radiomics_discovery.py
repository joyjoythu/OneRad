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


def test_low_confidence_narrows_to_ambiguous_medium_candidates(tmp_path):
    (tmp_path / "images" / "case_003").mkdir(parents=True)
    (tmp_path / "masks" / "case_003").mkdir(parents=True)
    (tmp_path / "images" / "case_003" / "T2.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_003" / "T2_seg.nii.gz").write_text("mask1")
    (tmp_path / "masks" / "case_003" / "T2_roi.nii.gz").write_text("mask2")
    (tmp_path / "masks" / "case_003" / "unrelated.nii.gz").write_text("mask3")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["low"]) == 1
    low = result["pairs"]["low"][0]
    assert low["patient_id"] == "case_003"
    assert low["sequence"] == "T2"
    candidates = low["candidates"]
    assert len(candidates) == 2
    assert "masks/case_003/T2_seg.nii.gz" in candidates
    assert "masks/case_003/T2_roi.nii.gz" in candidates
    assert "masks/case_003/unrelated.nii.gz" not in candidates


def test_low_confidence_unrelated_masks_are_unmatched(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()
    (tmp_path / "images" / "abc.nii.gz").write_text("img")
    (tmp_path / "masks" / "xyz_mask.nii.gz").write_text("mask1")
    (tmp_path / "masks" / "xyz_seg.nii.gz").write_text("mask2")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["low"]) == 0
    assert "images/abc.nii.gz" in result["unmatched_images"]
    assert "masks/xyz_mask.nii.gz" in result["unmatched_masks"]
    assert "masks/xyz_seg.nii.gz" in result["unmatched_masks"]


def test_returned_paths_are_project_relative(tmp_path):
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1.nii.gz").write_text("mask")
    (tmp_path / "masks" / "case_001" / "T2.nii.gz").write_text("unmatched_mask")

    result = discover_pairs(str(tmp_path))
    assert result["success"] is True

    high = result["pairs"]["high"][0]
    assert high["image_path"] == "images/case_001/T1.nii.gz"
    assert high["mask_path"] == "masks/case_001/T1.nii.gz"
    assert not Path(high["image_path"]).is_absolute()
    assert not Path(high["mask_path"]).is_absolute()

    assert result["unmatched_masks"] == ["masks/case_001/T2.nii.gz"]


def test_missing_images_dir(tmp_path):
    result = discover_pairs(str(tmp_path))
    assert result["success"] is False
    assert "images" in result["message"].lower()
