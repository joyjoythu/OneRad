import os
import h5py
import numpy as np
import yaml
import pytest
from unittest.mock import patch
from app.feature import FeatureAgent


@pytest.fixture
def yaml_path(tmp_path):
    p = tmp_path / "params.yaml"
    yaml.safe_dump({"setting": {"label": 1, "binWidth": 25}}, p.open("w"))
    return str(p)


@patch("app.feature.cir_get_features")
def test_feature_agent_outputs_h5(mock_extractor, tmp_path, yaml_path):
    mock_extractor.return_value = {"feature_a": 1.0, "feature_b": 2.0}

    out_dir = tmp_path / "out"
    img = tmp_path / "case_001_T1.nii.gz"
    mask = tmp_path / "case_001_T1_mask.nii.gz"
    img.write_text("img")
    mask.write_text("mask")

    pairs = [
        {"patient_id": "case_001", "image_path": str(img), "mask_path": str(mask)}
    ]

    agent = FeatureAgent(output_dir=str(out_dir))
    result = agent.run(pairs, yaml_path=yaml_path)

    assert result["success"] is True
    assert (out_dir / "radiomics_features.csv").exists()
    assert (out_dir / "h5" / "case_001_T1.h5").exists()

    with h5py.File(out_dir / "h5" / "case_001_T1.h5", "r") as f:
        assert "f_values" in f
        assert f["f_values"].shape == (1, 2)
        assert "feature_names" in f
        assert list(f["feature_names"].asstr()[:]) == ["feature_a", "feature_b"]
        assert f["patient_id"].asstr()[()] == "case_001"
        assert f["sequence"].asstr()[()] == ""


@patch("app.feature.cir_get_features")
def test_feature_agent_h5_nested_path(mock_extractor, tmp_path, yaml_path):
    """A single image under images/case_001/T1.nii.gz becomes case_001_T1.h5."""
    mock_extractor.return_value = {"feature_a": 1.0, "feature_b": 2.0}

    out_dir = tmp_path / "out"
    img_dir = tmp_path / "images" / "case_001"
    img_dir.mkdir(parents=True)
    img = img_dir / "T1.nii.gz"
    mask = img_dir / "T1_mask.nii.gz"
    img.write_text("img")
    mask.write_text("mask")

    pairs = [
        {"patient_id": "case_001", "image_path": str(img), "mask_path": str(mask)}
    ]

    result = FeatureAgent(output_dir=str(out_dir)).run(pairs, yaml_path=yaml_path)

    assert result["success"] is True
    h5_file = out_dir / "h5" / "case_001_T1.h5"
    assert h5_file.exists()

    with h5py.File(h5_file, "r") as f:
        assert f["f_values"].shape == (1, 2)
        assert f["f_values"].dtype == np.float64
        np.testing.assert_allclose(f["f_values"][:], [[1.0, 2.0]])
        assert list(f["feature_names"].asstr()[:]) == ["feature_a", "feature_b"]


@patch("app.feature.cir_get_features")
def test_feature_agent_h5_multiple_samples(mock_extractor, tmp_path, yaml_path):
    """Multiple patients each get their own h5 with correct names and values."""

    def extractor(image_path, mask_path, yaml_path):
        if "case_001" in image_path:
            return {"feature_a": 1.0, "feature_b": 2.0}
        return {"feature_a": 3.0, "feature_b": 4.0}

    mock_extractor.side_effect = extractor

    out_dir = tmp_path / "out"
    pairs = []
    for patient_id in ("case_001", "case_002"):
        img_dir = tmp_path / "images" / patient_id
        img_dir.mkdir(parents=True)
        img = img_dir / "T1.nii.gz"
        mask = img_dir / "T1_mask.nii.gz"
        img.write_text("img")
        mask.write_text("mask")
        pairs.append(
            {
                "patient_id": patient_id,
                "image_path": str(img),
                "mask_path": str(mask),
            }
        )

    result = FeatureAgent(output_dir=str(out_dir)).run(pairs, yaml_path=yaml_path)

    assert result["success"] is True
    assert result["feature_df"].shape == (2, 4)

    expected = {
        "case_001": [[1.0, 2.0]],
        "case_002": [[3.0, 4.0]],
    }
    for patient_id, values in expected.items():
        h5_file = out_dir / "h5" / f"{patient_id}_T1.h5"
        assert h5_file.exists(), f"missing {h5_file}"
        with h5py.File(h5_file, "r") as f:
            assert f["f_values"].shape == (1, 2)
            assert f["f_values"].dtype == np.float64
            np.testing.assert_allclose(f["f_values"][:], values)
            assert list(f["feature_names"].asstr()[:]) == ["feature_a", "feature_b"]


@patch("app.feature.cir_get_features")
def test_feature_agent_h5_failed_extraction(mock_extractor, tmp_path, yaml_path):
    """Failed cases must not produce h5 files and must be recorded in failed_cases.csv."""

    def extractor(image_path, mask_path, yaml_path):
        if "case_fail" in image_path:
            raise RuntimeError("mock extraction failure")
        return {"feature_a": 1.0, "feature_b": 2.0}

    mock_extractor.side_effect = extractor

    out_dir = tmp_path / "out"
    pairs = []
    for patient_id in ("case_ok", "case_fail"):
        img_dir = tmp_path / "images" / patient_id
        img_dir.mkdir(parents=True)
        img = img_dir / "T1.nii.gz"
        mask = img_dir / "T1_mask.nii.gz"
        img.write_text("img")
        mask.write_text("mask")
        pairs.append(
            {
                "patient_id": patient_id,
                "image_path": str(img),
                "mask_path": str(mask),
            }
        )

    result = FeatureAgent(output_dir=str(out_dir)).run(pairs, yaml_path=yaml_path)

    assert result["success"] is True
    assert result["failed_ids"] == ["case_fail"]

    # Successful case has an h5; failed case does not.
    assert (out_dir / "h5" / "case_ok_T1.h5").exists()
    assert not (out_dir / "h5" / "case_fail_T1.h5").exists()

    failed_csv = out_dir / "failed_cases.csv"
    assert failed_csv.exists()
    import pandas as pd

    df = pd.read_csv(failed_csv)
    assert list(df.columns) == ["patient_id", "image_path", "mask_path", "reason"]
    assert len(df) == 1
    assert df.loc[0, "patient_id"] == "case_fail"
    assert "case_fail" in df.loc[0, "image_path"]
    assert "case_fail" in df.loc[0, "mask_path"]
    assert "mock extraction failure" in df.loc[0, "reason"]


@patch("app.feature.cir_get_features")
def test_feature_agent_multi_sequence_same_patient(mock_extractor, tmp_path, yaml_path):
    """Multiple sequences for the same patient each get a distinct h5 file,
    and the CSV includes a sequence column with the correct values."""

    def extractor(image_path, mask_path, yaml_path):
        if "T1" in image_path:
            return {"feature_a": 1.0}
        return {"feature_a": 2.0}

    mock_extractor.side_effect = extractor

    out_dir = tmp_path / "out"
    pairs = []
    for sequence in ("T1", "T2"):
        img_dir = tmp_path / "images" / "case_001"
        img_dir.mkdir(parents=True, exist_ok=True)
        img = img_dir / f"{sequence}.nii.gz"
        mask = img_dir / f"{sequence}_mask.nii.gz"
        img.write_text("img")
        mask.write_text("mask")
        pairs.append(
            {
                "patient_id": "case_001",
                "sequence": sequence,
                "image_path": str(img),
                "mask_path": str(mask),
            }
        )

    result = FeatureAgent(output_dir=str(out_dir)).run(pairs, yaml_path=yaml_path)

    assert result["success"] is True
    assert result["feature_df"].shape == (2, 3)
    assert set(result["feature_df"]["sequence"]) == {"T1", "T2"}

    csv_path = out_dir / "radiomics_features.csv"
    assert csv_path.exists()
    import pandas as pd

    df = pd.read_csv(csv_path)
    assert "sequence" in df.columns
    assert set(df["sequence"]) == {"T1", "T2"}
    assert len(df) == 2

    for sequence in ("T1", "T2"):
        h5_file = out_dir / "h5" / f"case_001_{sequence}.h5"
        assert h5_file.exists(), f"missing {h5_file}"
        with h5py.File(h5_file, "r") as f:
            assert f["f_values"].shape == (1, 1)
            expected_value = 1.0 if sequence == "T1" else 2.0
            np.testing.assert_allclose(f["f_values"][:], [[expected_value]])
            assert list(f["feature_names"].asstr()[:]) == ["feature_a"]
