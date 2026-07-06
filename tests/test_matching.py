import pandas as pd
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
