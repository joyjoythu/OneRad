import pytest
import SimpleITK as sitk
import numpy as np
from pathlib import Path
from app.qc import QCAgent


def test_qc_empty_mask(tmp_path):
    # 创建空 mask
    img = sitk.GetImageFromArray(np.random.randint(0, 100, (10, 10, 10)).astype(np.int16))
    mask = sitk.GetImageFromArray(np.zeros((10, 10, 10), dtype=np.uint8))
    img_path = str(tmp_path / "img.nii.gz")
    mask_path = str(tmp_path / "mask.nii.gz")
    sitk.WriteImage(img, img_path)
    sitk.WriteImage(mask, mask_path)

    pairs = [{"patient_id": "P001", "image_path": img_path, "mask_path": mask_path, "modality": "CT"}]
    agent = QCAgent()
    result = agent.run(pairs)
    assert result["success"] is True
    assert result["passed"] == 0
    assert result["failed"] == 1
    assert result["failed_checks"][0]["fail_stage"] == "mask_empty"
