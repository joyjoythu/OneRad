import numpy as np
import SimpleITK as sitk

from app.image_spacing import inspect_spacing


def _write_nii(path, spacing, ndim=3):
    shape = (4, 5, 6) if ndim == 3 else (5, 6)
    img = sitk.GetImageFromArray(np.zeros(shape, dtype=np.uint8))
    img.SetSpacing(tuple(float(s) for s in spacing))
    sitk.WriteImage(img, str(path))


def test_scan_images_dir_summary(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    _write_nii(images / "a.nii.gz", (0.5, 0.5, 1.0))
    _write_nii(images / "b.nii.gz", (1.0, 1.0, 2.0))
    result = inspect_spacing(str(tmp_path))
    assert result["success"] is True
    assert result["n_cases"] == 2
    assert result["suggested_spacing"] == [0.75, 0.75, 1.5]
    assert result["summary"]["min"] == [0.5, 0.5, 1.0]
    assert result["summary"]["max"] == [1.0, 1.0, 2.0]
    assert result["failed"] == []
    assert len(result["cases"]) == 2


def test_image_paths_filter_and_relative_display(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    kept = images / "kept.nii.gz"
    _write_nii(kept, (0.4, 0.4, 0.4))
    _write_nii(images / "other.nii.gz", (2.0, 2.0, 2.0))
    result = inspect_spacing(str(tmp_path), image_paths=[str(kept)])
    assert result["n_cases"] == 1
    assert result["cases"][0]["path"] == "images/kept.nii.gz"


def test_unreadable_and_2d_go_to_failed(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "bad.nii.gz").write_bytes(b"not a nifti")
    _write_nii(images / "2d.nii.gz", (1.0, 1.0), ndim=2)
    _write_nii(images / "good.nii.gz", (1.0, 1.0, 1.0))
    result = inspect_spacing(str(tmp_path))
    assert result["success"] is True
    assert result["n_cases"] == 1
    assert len(result["failed"]) == 2


def test_no_images_returns_failure(tmp_path):
    assert inspect_spacing(str(tmp_path))["success"] is False
    (tmp_path / "images").mkdir()
    assert inspect_spacing(str(tmp_path))["success"] is False


def test_cases_truncated_over_50(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for i in range(55):
        _write_nii(images / f"case_{i:03d}.nii.gz", (1.0, 1.0, 1.0))
    result = inspect_spacing(str(tmp_path))
    assert result["n_cases"] == 55
    assert "cases" not in result
    assert result["cases_truncated"] is True
