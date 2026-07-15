import os
import h5py
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
