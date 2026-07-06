import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import SimpleITK as sitk
import numpy as np

logger = logging.getLogger(__name__)


class QCAgent:
    """Quality-control agent for medical image / mask pairs.

    Performs geometric alignment checks, optional resampling to a target
    spacing, and basic intensity validation for CT and MRI volumes.
    """

    def __init__(self, target_spacing: Optional[Tuple[float, float, float]] = None,
                 output_dir: str = "./output/qc_resampled"):
        self.target_spacing = self._validate_target_spacing(target_spacing)
        self.output_dir = Path(output_dir)

    def _validate_target_spacing(
        self, target_spacing: Optional[Tuple[float, float, float]]
    ) -> Optional[Tuple[float, float, float]]:
        """Validate ``target_spacing`` when provided.

        Must be a tuple/list of exactly three positive floats. Returns the
        spacing as a tuple of floats, or ``None`` when not provided.
        """
        if target_spacing is None:
            return None
        if not isinstance(target_spacing, (tuple, list)):
            raise ValueError("target_spacing must be a tuple or list of 3 positive floats")
        if len(target_spacing) != 3:
            raise ValueError("target_spacing must contain exactly 3 values")
        if not all(np.isscalar(s) and not isinstance(s, bool) and float(s) > 0 for s in target_spacing):
            raise ValueError("target_spacing must contain positive floats")
        return tuple(float(s) for s in target_spacing)

    @staticmethod
    def _spacing_equal(a: Tuple[float, ...], b: Tuple[float, ...], tol: float = 1e-4) -> bool:
        """Return True if two spacings match within ``tol`` for all dimensions."""
        return len(a) == len(b) and all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))

    @staticmethod
    def _origin_equal(a: Tuple[float, ...], b: Tuple[float, ...], tol: float = 1e-4) -> bool:
        """Return True if two origins match within ``tol`` for all dimensions."""
        return len(a) == len(b) and all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))

    @staticmethod
    def _direction_equal(a: Tuple[float, ...], b: Tuple[float, ...], tol: float = 1e-4) -> bool:
        """Return True if two direction cosine matrices match within ``tol``."""
        return len(a) == len(b) and all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))

    def run(self, pairs: List[Dict[str, str]]) -> Dict[str, Any]:
        """Run QC checks on a batch of image/mask pairs.

        Returns an aggregation containing pass/fail counts, passed pair
        metadata, and detailed failure records.
        """
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
            "passed": len(passed),
            "failed": len(failed),
            "passed_pairs": passed_pairs,
            "failed_checks": failed,
            "resampled": any(r.get("resampled", False) for r in passed),
            "original_spacings": [r.get("original_spacing") for r in results],
        }

    def _check_single(self, pair: Dict[str, str]) -> Dict[str, Any]:
        """Run all QC checks on a single image/mask pair.

        Checks include: non-empty mask, dimension match, geometric alignment
        (spacing/origin/direction), optional resampling to ``target_spacing``,
        finite intensity values, and modality-specific intensity rules.

        The returned dict always contains ``shape`` (the current image size,
        updated after any resampling). When resampling occurs, either for
        geometric alignment or to reach ``target_spacing``, ``resampled`` is
        ``True`` and ``resampled_shape`` records the image size after the
        resampling step.
        """
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
                logger.warning("[%s] Mask is empty (no ROI)", pair["patient_id"])
                return self._fail(result, "mask_empty", "Mask 全零，无 ROI")
            result["roi_voxel_count"] = int(roi)

            # 尺寸一致
            if image.GetSize() != mask.GetSize():
                logger.warning(
                    "[%s] Dimension mismatch: image %s vs mask %s",
                    pair["patient_id"], image.GetSize(), mask.GetSize()
                )
                return self._fail(result, "dimension", f"尺寸不一致: {image.GetSize()} vs {mask.GetSize()}")

            # spacing / origin / direction 对齐
            spacing_aligned = self._spacing_equal(image.GetSpacing(), mask.GetSpacing())
            origin_aligned = self._origin_equal(image.GetOrigin(), mask.GetOrigin())
            direction_aligned = self._direction_equal(image.GetDirection(), mask.GetDirection())
            if not (spacing_aligned and origin_aligned and direction_aligned):
                logger.warning(
                    "[%s] Geometric mismatch detected (spacing=%s, origin=%s, direction=%s); "
                    "resampling mask to image grid",
                    pair["patient_id"], spacing_aligned, origin_aligned, direction_aligned
                )
                mask = self._resample_to_reference(mask, image, is_mask=True)
                result["resampled"] = True
                result["shape"] = image.GetSize()
                result["resampled_shape"] = image.GetSize()

            # 目标 spacing resample
            if self.target_spacing and not self._spacing_equal(image.GetSpacing(), self.target_spacing):
                logger.info(
                    "[%s] Resampling image and mask to target spacing %s",
                    pair["patient_id"], self.target_spacing
                )
                modality = pair.get("modality", "unknown")
                img_out = self.output_dir / f"{pair['patient_id']}_{modality}_image.nii.gz"
                mask_out = self.output_dir / f"{pair['patient_id']}_{modality}_mask.nii.gz"
                image = self._resample_to_spacing(image, self.target_spacing, is_mask=False)
                mask = self._resample_to_spacing(mask, self.target_spacing, is_mask=True)
                sitk.WriteImage(image, str(img_out))
                sitk.WriteImage(mask, str(mask_out))
                result["resampled_image_path"] = str(img_out)
                result["resampled_mask_path"] = str(mask_out)
                result["resampled"] = True
                result["shape"] = image.GetSize()
                result["resampled_shape"] = image.GetSize()

            # 值域检查
            img_arr = sitk.GetArrayFromImage(image)
            if not np.all(np.isfinite(img_arr)):
                logger.warning("[%s] Image contains NaN/Inf values", pair["patient_id"])
                return self._fail(result, "value_range", "影像包含 NaN/Inf")

            if result["modality"].upper() == "CT":
                if img_arr.min() < -1000 or img_arr.max() > 3000:
                    msg = "CT HU 值域超出常见范围，仅警告"
                    logger.warning("[%s] %s", pair["patient_id"], msg)
                    result["messages"].append(msg)
            elif result["modality"].upper() == "MRI":
                unique_ratio = len(np.unique(img_arr)) / img_arr.size
                if unique_ratio < 0.001:
                    logger.warning("[%s] MRI signal too homogeneous", pair["patient_id"])
                    return self._fail(result, "value_range", "MRI 信号过于单一")

            result["messages"].append("全部 QC 检查通过")
            return result
        except Exception as e:
            logger.exception("[%s] QC raised an exception", pair["patient_id"])
            return self._fail(result, "exception", str(e))

    def _fail(self, result: Dict[str, Any], stage: str, reason: str) -> Dict[str, Any]:
        result["status"] = "failed"
        result["fail_stage"] = stage
        result["fail_reason"] = reason
        result["messages"].append(f"FAIL[{stage}]: {reason}")
        return result

    def _resample_to_spacing(
        self, image: sitk.Image, target: Tuple[float, float, float], is_mask: bool
    ) -> sitk.Image:
        """Resample an image to a requested isotropic/anisotropic spacing."""
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

    def _resample_to_reference(
        self, image: sitk.Image, reference: sitk.Image, is_mask: bool
    ) -> sitk.Image:
        """Resample ``image`` into the exact grid of ``reference``."""
        interp = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear
        resampler = sitk.ResampleImageFilter()
        resampler.SetReferenceImage(reference)
        resampler.SetInterpolator(interp)
        resampler.SetDefaultPixelValue(0)
        return resampler.Execute(image)
