# Task 10: 实现 QC Agent

### Task 10: 实现 QC Agent

**Files:**
- Create: `app/qc.py`
- Create: `tests/test_qc.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_qc.py`:
```python
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
```

- [ ] **Step 2: 实现 QCAgent**

`app/qc.py`:
```python
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import SimpleITK as sitk
import numpy as np

logger = logging.getLogger(__name__)


class QCAgent:
    def __init__(self, target_spacing: Optional[Tuple[float, float, float]] = None,
                 output_dir: str = "./output/qc_resampled"):
        self.target_spacing = target_spacing
        self.output_dir = Path(output_dir)

    def run(self, pairs: List[Dict[str, str]]) -> Dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for p in pairs:
            results.append(self._check_single(p))

        passed = [r for r in results if r["status"] == "passed"]
        failed = [r for r in results if r["status"] == "failed"]

        passed_pairs = []
        for r in passed:
            passed_pairs.append({
                "patient_id": r["patient_id"],
                "image_path": str(r.get("resampled_image_path", r["image_path"])),
                "mask_path": str(r.get("resampled_mask_path", r["mask_path"])),
                "modality": r["modality"],
            })

        return {
            "success": True,
            "message": f"QC 完成: {len(passed)} 通过, {len(failed)} 失败",
            "passed_pairs": passed_pairs,
            "failed_checks": failed,
            "resampled": any(r.get("resampled", False) for r in passed),
            "original_spacings": [r.get("original_spacing") for r in results],
        }

    def _check_single(self, pair: Dict[str, str]) -> Dict[str, Any]:
        result = {
            "patient_id": pair["patient_id"],
            "image_path": pair["image_path"],
            "mask_path": pair["mask_path"],
            "modality": pair.get("modality", "CT"),
            "status": "passed",
            "messages": [],
            "resampled": False,
        }
        try:
            image = sitk.ReadImage(pair["image_path"])
            mask = sitk.ReadImage(pair["mask_path"])

            result["original_spacing"] = image.GetSpacing()
            result["shape"] = image.GetSize()

            # mask 非空
            mask_arr = sitk.GetArrayFromImage(mask)
            roi = np.count_nonzero(mask_arr > 0)
            if roi == 0:
                return self._fail(result, "mask_empty", "Mask 全零，无 ROI")
            result["roi_voxel_count"] = int(roi)

            # 尺寸一致
            if image.GetSize() != mask.GetSize():
                return self._fail(result, "dimension", f"尺寸不一致: {image.GetSize()} vs {mask.GetSize()}")

            # spacing 对齐
            if image.GetSpacing() != mask.GetSpacing():
                mask = self._resample_to_reference(mask, image, is_mask=True)

            # 目标 spacing resample
            if self.target_spacing and image.GetSpacing() != tuple(self.target_spacing):
                img_out = self.output_dir / f"{pair['patient_id']}_image.nii.gz"
                mask_out = self.output_dir / f"{pair['patient_id']}_mask.nii.gz"
                image = self._resample_to_spacing(image, tuple(self.target_spacing), is_mask=False)
                mask = self._resample_to_spacing(mask, tuple(self.target_spacing), is_mask=True)
                sitk.WriteImage(image, str(img_out))
                sitk.WriteImage(mask, str(mask_out))
                result["resampled_image_path"] = str(img_out)
                result["resampled_mask_path"] = str(mask_out)
                result["resampled"] = True

            # 值域检查
            img_arr = sitk.GetArrayFromImage(image)
            if not np.all(np.isfinite(img_arr)):
                return self._fail(result, "value_range", "影像包含 NaN/Inf")

            if result["modality"].upper() == "CT":
                if img_arr.min() < -1000 or img_arr.max() > 3000:
                    result["messages"].append("CT HU 值域超出常见范围，仅警告")
            elif result["modality"].upper() == "MRI":
                unique_ratio = len(np.unique(img_arr)) / img_arr.size
                if unique_ratio < 0.001:
                    return self._fail(result, "value_range", "MRI 信号过于单一")

            result["messages"].append("全部 QC 检查通过")
            return result
        except Exception as e:
            return self._fail(result, "exception", str(e))

    def _fail(self, result: Dict[str, Any], stage: str, reason: str) -> Dict[str, Any]:
        result["status"] = "failed"
        result["fail_stage"] = stage
        result["fail_reason"] = reason
        result["messages"].append(f"FAIL[{stage}]: {reason}")
        return result

    def _resample_to_spacing(self, image: sitk.Image, target: Tuple[float, float, float], is_mask: bool) -> sitk.Image:
        size = image.GetSize()
        spacing = image.GetSpacing()
        new_size = [max(1, int(round(size[i] * spacing[i] / target[i]))) for i in range(3)]
        interp = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear
        resampler = sitk.ResampleImageFilter()
        resampler.SetOutputSpacing(target)
        resampler.SetSize(new_size)
        resampler.SetOutputOrigin(image.GetOrigin())
        resampler.SetOutputDirection(image.GetDirection())
        resampler.SetInterpolator(interp)
        resampler.SetDefaultPixelValue(0)
        return resampler.Execute(image)

    def _resample_to_reference(self, image: sitk.Image, reference: sitk.Image, is_mask: bool) -> sitk.Image:
        interp = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear
        resampler = sitk.ResampleImageFilter()
        resampler.SetReferenceImage(reference)
        resampler.SetInterpolator(interp)
        resampler.SetDefaultPixelValue(0)
        return resampler.Execute(image)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_qc.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/qc.py tests/test_qc.py
git commit -m "feat: add QCAgent with mask/dimension/spacing/value checks"
```

---
