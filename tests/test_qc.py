import pytest
import SimpleITK as sitk
import numpy as np
from pathlib import Path
from app.qc import QCAgent


def _write_pair(tmp_path: Path, patient_id: str, img_arr: np.ndarray, mask_arr: np.ndarray,
                modality: str = "CT", img_spacing=(1.0, 1.0, 1.0), mask_spacing=(1.0, 1.0, 1.0),
                mask_origin=None, mask_direction=None):
    """Create an image/mask NIfTI pair and return the pair dict."""
    image = sitk.GetImageFromArray(img_arr.astype(np.float32))
    mask = sitk.GetImageFromArray(mask_arr.astype(np.uint8))
    image.SetSpacing(img_spacing)
    mask.SetSpacing(mask_spacing)
    if mask_origin is not None:
        mask.SetOrigin(mask_origin)
    if mask_direction is not None:
        mask.SetDirection(mask_direction)

    img_path = str(tmp_path / f"{patient_id}_{modality}_image.nii.gz")
    mask_path = str(tmp_path / f"{patient_id}_{modality}_mask.nii.gz")
    sitk.WriteImage(image, img_path)
    sitk.WriteImage(mask, mask_path)

    return {
        "patient_id": patient_id,
        "image_path": img_path,
        "mask_path": mask_path,
        "modality": modality,
    }


def test_qc_empty_mask(tmp_path):
    img_arr = np.random.randint(0, 100, (10, 10, 10)).astype(np.int16)
    mask_arr = np.zeros((10, 10, 10), dtype=np.uint8)
    pair = _write_pair(tmp_path, "P001", img_arr, mask_arr, modality="CT")

    agent = QCAgent()
    result = agent.run([pair])
    assert result["success"] is True
    assert result["passed"] == 0
    assert result["failed"] == 1
    assert result["failed_checks"][0]["fail_stage"] == "mask_empty"


def test_qc_dimension_mismatch_failure(tmp_path):
    img_arr = np.random.randint(0, 100, (10, 10, 10)).astype(np.int16)
    mask_arr = np.zeros((8, 8, 8), dtype=np.uint8)
    mask_arr[2:6, 2:6, 2:6] = 1
    pair = _write_pair(tmp_path, "P002", img_arr, mask_arr, modality="CT")

    agent = QCAgent()
    result = agent.run([pair])
    assert result["failed"] == 1
    assert result["failed_checks"][0]["fail_stage"] == "dimension"


def test_qc_spacing_mismatch_resamples_mask(tmp_path):
    # Same array size but different spacing -> mask resampled to image grid
    img_arr = np.random.randint(0, 100, (10, 10, 10)).astype(np.int16)
    mask_arr = np.zeros((10, 10, 10), dtype=np.uint8)
    mask_arr[3:7, 3:7, 3:7] = 1
    pair = _write_pair(
        tmp_path, "P003", img_arr, mask_arr,
        modality="CT", img_spacing=(1.0, 1.0, 1.0), mask_spacing=(0.5, 0.5, 0.5)
    )

    agent = QCAgent()
    result = agent.run([pair])
    assert result["passed"] == 1
    assert result["failed"] == 0
    # Mask was geometrically realigned, so the run is considered resampled.
    assert result["resampled"] is True

    single = agent._check_single(pair)
    assert single["shape"] == (10, 10, 10)
    assert single["resampled_shape"] == (10, 10, 10)


def test_qc_origin_direction_mismatch_resamples_mask(tmp_path):
    img_arr = np.random.randint(0, 100, (10, 10, 10)).astype(np.int16)
    mask_arr = np.zeros((10, 10, 10), dtype=np.uint8)
    mask_arr[3:7, 3:7, 3:7] = 1
    pair = _write_pair(
        tmp_path, "P003b", img_arr, mask_arr,
        modality="CT", mask_origin=(0.5, 0.5, 0.5),
        mask_direction=(0.9999, 0.0, 0.0, 0.0, 0.9999, 0.0, 0.0, 0.0, 0.9999)
    )

    agent = QCAgent()
    result = agent.run([pair])
    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["resampled"] is True

    single = agent._check_single(pair)
    assert single["shape"] == (10, 10, 10)
    assert single["resampled_shape"] == (10, 10, 10)


def test_qc_geometric_mismatch_persists_corrected_mask(tmp_path):
    # Same array size but mismatched spacing -> mask is geometrically corrected
    # and written to disk so downstream agents use the corrected mask.
    img_arr = np.random.randint(0, 100, (10, 10, 10)).astype(np.int16)
    mask_arr = np.zeros((10, 10, 10), dtype=np.uint8)
    mask_arr[3:7, 3:7, 3:7] = 1
    pair = _write_pair(
        tmp_path, "P010", img_arr, mask_arr,
        modality="CT", img_spacing=(1.0, 1.0, 1.0), mask_spacing=(0.5, 0.5, 0.5)
    )

    out_dir = tmp_path / "qc_out"
    agent = QCAgent(output_dir=str(out_dir))
    result = agent.run([pair])

    assert result["passed"] == 1
    corrected_mask_path = Path(result["passed_pairs"][0]["mask_path"])
    assert corrected_mask_path.exists()
    assert corrected_mask_path.parent == out_dir
    assert corrected_mask_path != Path(pair["mask_path"])

    corrected_mask = sitk.ReadImage(str(corrected_mask_path))
    image = sitk.ReadImage(pair["image_path"])
    assert np.allclose(corrected_mask.GetSpacing(), image.GetSpacing())
    assert np.allclose(corrected_mask.GetOrigin(), image.GetOrigin())
    assert np.allclose(corrected_mask.GetDirection(), image.GetDirection())


def test_qc_target_spacing_resampling_and_file_output(tmp_path):
    img_arr = np.random.randint(-200, 400, (20, 20, 20)).astype(np.int16)
    mask_arr = np.zeros((20, 20, 20), dtype=np.uint8)
    mask_arr[8:14, 8:14, 8:14] = 1
    pair = _write_pair(
        tmp_path, "P004", img_arr, mask_arr,
        modality="CT", img_spacing=(1.0, 1.0, 1.0)
    )

    out_dir = tmp_path / "resampled"
    agent = QCAgent(target_spacing=(2.0, 2.0, 2.0), output_dir=str(out_dir))
    result = agent.run([pair])

    assert result["passed"] == 1
    assert result["resampled"] is True
    expected_img = out_dir / "P004_CT_image.nii.gz"
    expected_mask = out_dir / "P004_CT_mask.nii.gz"
    assert expected_img.exists()
    assert expected_mask.exists()

    resampled = sitk.ReadImage(str(expected_img))
    assert np.allclose(resampled.GetSpacing(), (2.0, 2.0, 2.0))
    single = agent._check_single(pair)
    assert single["shape"] == resampled.GetSize()
    assert single["resampled_shape"] == resampled.GetSize()


def test_qc_nan_inf_failure(tmp_path, monkeypatch):
    # SimpleITK may sanitize NaN/Inf when writing NIfTI, so inject the corrupted
    # image directly into _check_single via a patched ReadImage.
    img_arr = np.random.randint(0, 100, (10, 10, 10)).astype(np.float32)
    img_arr[5, 5, 5] = np.nan
    mask_arr = np.zeros((10, 10, 10), dtype=np.uint8)
    mask_arr[3:7, 3:7, 3:7] = 1
    pair = _write_pair(tmp_path, "P005", img_arr, mask_arr, modality="CT")

    nan_image = sitk.GetImageFromArray(img_arr)
    mask_image = sitk.ReadImage(pair["mask_path"])

    def mock_read(path):
        if path == pair["image_path"]:
            return nan_image
        return mask_image

    monkeypatch.setattr(sitk, "ReadImage", mock_read)

    agent = QCAgent()
    result = agent.run([pair])
    assert result["failed"] == 1
    assert result["failed_checks"][0]["fail_stage"] == "value_range"


def test_qc_ct_hu_warning(tmp_path):
    # When CT intensities fall outside the common -1000..3000 HU range,
    # a warning message is appended to the QC record.
    img_arr = np.random.randint(-1200, 3200, (10, 10, 10)).astype(np.int16)
    mask_arr = np.zeros((10, 10, 10), dtype=np.uint8)
    mask_arr[3:7, 3:7, 3:7] = 1
    pair = _write_pair(tmp_path, "P006", img_arr, mask_arr, modality="CT")

    agent = QCAgent()
    result = agent.run([pair])
    assert result["passed"] == 1
    # The run summary does not expose per-record messages, so inspect the single record.
    single = agent._check_single(pair)
    assert any("CT HU" in msg for msg in single["messages"])


def test_qc_mri_low_unique_value_failure(tmp_path):
    # Mostly constant MRI signal in a large enough volume -> unique ratio < 0.001
    img_arr = np.full((20, 20, 20), 50, dtype=np.float32)
    mask_arr = np.zeros((20, 20, 20), dtype=np.uint8)
    mask_arr[5:15, 5:15, 5:15] = 1
    pair = _write_pair(tmp_path, "P007", img_arr, mask_arr, modality="MRI")

    agent = QCAgent()
    result = agent.run([pair])
    assert result["failed"] == 1
    assert result["failed_checks"][0]["fail_stage"] == "value_range"


def test_qc_multi_pair_batch_aggregation(tmp_path):
    # Pair 1: passes
    img1 = np.random.randint(-200, 400, (10, 10, 10)).astype(np.int16)
    mask1 = np.zeros((10, 10, 10), dtype=np.uint8)
    mask1[3:7, 3:7, 3:7] = 1
    pair1 = _write_pair(tmp_path, "P008", img1, mask1, modality="CT")

    # Pair 2: fails (empty mask)
    img2 = np.random.randint(0, 100, (10, 10, 10)).astype(np.int16)
    mask2 = np.zeros((10, 10, 10), dtype=np.uint8)
    pair2 = _write_pair(tmp_path, "P009", img2, mask2, modality="CT")

    agent = QCAgent()
    result = agent.run([pair1, pair2])
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert len(result["passed_pairs"]) == 1
    assert result["passed_pairs"][0]["patient_id"] == "P008"
    assert len(result["failed_checks"]) == 1
    assert result["failed_checks"][0]["patient_id"] == "P009"


@pytest.mark.parametrize("bad_spacing", [
    "not-a-list",
    (1.0, 2.0),
    (1.0, 2.0, -3.0),
    (1.0, 2.0, 0.0),
    [1.0, "two", 3.0],
])
def test_qc_invalid_target_spacing_raises(bad_spacing):
    with pytest.raises(ValueError):
        QCAgent(target_spacing=bad_spacing)


def test_qc_numpy_scalar_target_spacing_accepted():
    agent = QCAgent(target_spacing=(np.float64(1.0), np.int64(2), 3.0))
    assert agent.target_spacing == (1.0, 2.0, 3.0)
