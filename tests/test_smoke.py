import os

import numpy as np
import pandas as pd
import pytest
import SimpleITK as sitk

from app.orchestrator import Orchestrator, PipelineStage, register_default_handlers


@pytest.fixture
def deterministic_rng():
    """Reset NumPy RNG for deterministic synthetic features."""
    return np.random.default_rng(42)


def test_smoke_pipeline(tmp_path, deterministic_rng):
    # 1. Build temporary image directory with valid 3D NIfTI image/mask pairs.
    img_dir = tmp_path / "images"
    img_dir.mkdir()

    patient_ids = [f"P{i:03d}" for i in range(1, 21)]
    labels = [0] * 10 + [1] * 10

    for pid in patient_ids:
        img_arr = deterministic_rng.integers(0, 100, size=(8, 8, 8)).astype(np.int16)
        mask_arr = np.ones((8, 8, 8), dtype=np.uint8)
        img = sitk.GetImageFromArray(img_arr)
        mask = sitk.GetImageFromArray(mask_arr)
        sitk.WriteImage(img, str(img_dir / f"{pid}_image.nii.gz"))
        sitk.WriteImage(mask, str(img_dir / f"{pid}_mask.nii.gz"))

    # 2. Build temporary clinical CSV.
    clinical_path = tmp_path / "clinical.csv"
    clinical_df = pd.DataFrame({
        "PatientID": patient_ids,
        "Age": list(range(30, 50)),
        "Label": labels,
    })
    clinical_df.to_csv(clinical_path, index=False)

    # 3. Instantiate orchestrator with a low min_samples threshold.
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")

    output_dir = tmp_path / "output"

    orch = Orchestrator(
        image_dir=str(img_dir),
        clinical_path=str(clinical_path),
        output_dir=str(output_dir),
        yaml_path=str(yaml_path),
        min_samples=5,
    )
    register_default_handlers(orch)

    # 4. Mock ClinicalAgent.run to skip real LLM calls.
    import app.clinical as clinical_module

    original_clinical_run = clinical_module.ClinicalAgent.run

    def mock_clinical_run(self, clinical_path, task_hint=""):
        return {
            "success": True,
            "message": "mock clinical",
            "df": clinical_df.copy(),
            "id_col": "PatientID",
            "label_col": "Label",
            "feature_cols": ["Age"],
            "id_dtype": "str",
            "n_samples": len(clinical_df),
        }

    clinical_module.ClinicalAgent.run = mock_clinical_run

    # 5. Mock FeatureAgent.run to return a synthetic radiomic feature matrix.
    import app.feature as feature_module

    original_feature_run = feature_module.FeatureAgent.run

    def mock_feature_run(self, pairs, yaml_path, n_jobs=-1):
        rows = []
        for p in pairs:
            pid = p["patient_id"]
            label = clinical_df.loc[clinical_df["PatientID"] == pid, "Label"].values[0]
            # One perfectly separable radiomic feature plus a few noisy ones so
            # LASSO consistently selects at least one feature in every fold.
            rows.append({
                "patient_id": pid,
                "original_firstorder_Mean": float(label * 100.0 + deterministic_rng.random()),
                "original_firstorder_Variance": float(deterministic_rng.random() * 10.0),
                "original_shape_VoxelVolume": 2.0,
                "original_glcm_JointEntropy": float(deterministic_rng.random()),
                "wavelet-LHL_firstorder_Mean": float(deterministic_rng.random()),
            })
        feature_df = pd.DataFrame(rows).set_index("patient_id")
        return {
            "success": True,
            "message": "mock feature extraction",
            "feature_df": feature_df,
            "feature_names": feature_df.columns.tolist(),
            "failed_ids": [],
            "zero_variance_features": [],
            "settings_used": {},
            "extraction_time_seconds": 0.1,
        }

    feature_module.FeatureAgent.run = mock_feature_run

    try:
        events = list(orch.run())
    finally:
        # Always restore original methods, even on failure.
        clinical_module.ClinicalAgent.run = original_clinical_run
        feature_module.FeatureAgent.run = original_feature_run

    # 6. Assert pipeline completed successfully and produced a report.
    assert orch.state["stage"] == PipelineStage.COMPLETED
    assert orch.state["report"]["success"] is True

    expected_report_path = os.path.join(str(output_dir), "AutoRadiomics_Report.docx")
    assert orch.state["report"]["report_path"] == expected_report_path
    assert os.path.exists(expected_report_path)

    # Sanity checks on intermediate stages.
    assert orch.state["discovery"]["success"] is True
    assert orch.state["clinical"]["success"] is True
    assert orch.state["matching"]["success"] is True
    assert orch.state["qc"]["success"] is True
    assert orch.state["feature"]["success"] is True
    assert orch.state["merged"]["success"] is True
    assert orch.state["analysis"]["success"] is True
