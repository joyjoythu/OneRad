import yaml
from pathlib import Path
from unittest.mock import patch
from app.radiomics_discovery import discover_pairs
from app.feature import FeatureAgent


def test_end_to_end_discovery_and_extraction(tmp_path, monkeypatch):
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1.nii.gz").write_text("mask")

    yaml_path = tmp_path / "Params_labels.yaml"
    yaml.safe_dump({"setting": {"label": 1, "binWidth": 25}}, yaml_path.open("w"))

    discovery = discover_pairs(str(tmp_path))
    assert discovery["success"]
    pairs = discovery["pairs"]["high"]

    # FeatureAgent resolves relative image/mask paths from the working directory.
    monkeypatch.chdir(tmp_path)

    with patch("app.feature.cir_get_features") as mock_extract:
        mock_extract.return_value = {"original_firstorder_Mean": 1.0}
        agent = FeatureAgent(output_dir=str(tmp_path / "radiomics_features"))
        result = agent.run(pairs, yaml_path=str(yaml_path))

    assert result["success"]
    assert (tmp_path / "radiomics_features" / "radiomics_features.csv").exists()
    assert (tmp_path / "radiomics_features" / "h5" / "case_001_T1.h5").exists()
